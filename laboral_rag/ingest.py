"""Pipeline de ingesta reproducible (enunciado §5.3):
carga → extracción → limpieza → segmentación por artículo → metadatos → indexación.

Uso:  python -m laboral_rag.ingest
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import settings
from .schemas import Chunk, UserRole
from .text import clean_page_text, remove_repeated_lines

# Un artículo empieza con "Artículo 82." / "ARTICULO 82" / "Artículo 82 bis" al inicio de línea.
ARTICLE_RE = re.compile(r"(?im)^\s*(?:#+\s*)?art[ií]culo\s+(\d+(?:\s*bis)?)\s*[.:\-–]?")
MAX_CHARS = 1800  # artículos más largos se subdividen
OVERLAP = 200


def _is_real_article_header(full: str, m: re.Match) -> bool:
    nl = full.find("\n", m.end())
    rest = full[m.end(): nl if nl != -1 else len(full)]
    rest = re.sub(r"^[\s.]*\d+", "", rest, count=1)  
    return bool(re.search(r"[^\W\d_]", rest))  


@dataclass
class SourceMeta:
    file: str
    title: str
    version: str
    access: list[UserRole]
    owner: str = ""
    url: str = ""
    license: str = ""
    sensitivity: str = "publica"
    update_frequency: str = ""
    vigente: bool = True


# ---------- 1. Carga ----------
def load_manifest(path: Path = settings.sources_manifest) -> list[SourceMeta]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for s in data["sources"]:
        s = dict(s)
        s["access"] = [UserRole(r) for r in s.get("access", ["colaborador", "rrhh"])]
        out.append(SourceMeta(**{k: v for k, v in s.items() if k in SourceMeta.__dataclass_fields__}))
    return out


# ---------- 2. Extracción ----------
def extract_pages(path: Path) -> list[str]:
    """Devuelve una lista con el texto de cada página. Markdown/txt se tratan como una sola página
    salvo que usen el marcador '<!-- page N -->'."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [p.extract_text() or "" for p in reader.pages]
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"<!--\s*page\s*\d+\s*-->", text)
    if len(parts) > 1:  # lo que va antes del primer marcador (título) pertenece a la página 1
        parts = [parts[0] + "\n" + parts[1]] + parts[2:]
    return [p for p in parts if p.strip()] or [text]


# ---------- 3. Limpieza ----------
def clean_pages(pages: list[str]) -> list[str]:
    return remove_repeated_lines([clean_page_text(p) for p in pages])


# ---------- 4. Segmentación ----------
def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + MAX_CHARS)
        if end < len(text):  # cortar en el último salto de párrafo/oración dentro de la ventana
            cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if cut > start + MAX_CHARS // 2:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return parts


def segment(pages: list[str]) -> list[tuple[str, int, str | None]]:
    """Segmenta por artículo (unidad semántica natural de un cuerpo legal).
    Devuelve (texto, página_inicio, número_de_artículo)."""
    full, offsets = "", []
    for i, p in enumerate(pages, start=1):
        offsets.append((len(full), i))
        full += p + "\n\n"

    def page_at(pos: int) -> int:
        page = 1
        for off, pg in offsets:
            if off <= pos:
                page = pg
        return page

    matches = [m for m in ARTICLE_RE.finditer(full) if _is_real_article_header(full, m)]
    segments: list[tuple[str, int, str | None]] = []
    if not matches:  # documento sin artículos: partir por párrafos/ventana
        for part in _split_long(full.strip()):
            segments.append((part, page_at(full.find(part[:50])), None))
        return segments

    preamble = full[: matches[0].start()].strip()
    if len(preamble) > 80:
        for part in _split_long(preamble):
            segments.append((part, 1, None))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        body = full[m.start() : end].strip()
        art = re.sub(r"\s+", " ", m.group(1)).lower()
        for part in _split_long(body):
            segments.append((part, page_at(m.start()), art))
    return segments


# ---------- 5. Metadatos ----------
def build_chunks(meta: SourceMeta, segments: list[tuple[str, int, str | None]]) -> list[Chunk]:
    stem = Path(meta.file).stem
    chunks = []
    for i, (text, page, art) in enumerate(segments):
        chunks.append(
            Chunk(
                chunk_id=f"{stem}::{i:04d}",
                text=text,
                source=meta.file,
                page=page,
                version=meta.version,
                title=meta.title,
                article=art,
                access=meta.access,
                hash=hashlib.sha256(text.encode()).hexdigest()[:16],
                vigente=meta.vigente,
            )
        )
    return chunks


# ---------- 6. Indexación ----------
def write_index(chunks: list[Chunk], index_dir: Path = settings.index_dir, with_embeddings: bool = True) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    with (index_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(c.model_dump_json() + "\n")
    if with_embeddings and settings.retrieval_mode in ("dense", "hybrid"):
        try:
            import numpy as np

            from .retrieval import get_embedder

            emb = get_embedder().encode([c.text for c in chunks], normalize_embeddings=True, show_progress_bar=True)
            np.save(index_dir / "embeddings.npy", emb)
        except ImportError:
            print("[ingest] sentence-transformers no instalado: solo se generó el índice léxico (BM25).")


def run(raw_dir: Path = settings.raw_dir, index_dir: Path = settings.index_dir, with_embeddings: bool = True) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    report = []
    for meta in load_manifest():
        path = raw_dir / meta.file
        if not path.exists():
            print(f"[ingest] FALTA {path.name}: descárgalo (ver data/README.md). Se omite.")
            continue
        pages = clean_pages(extract_pages(path))
        segs = segment(pages)
        chunks = build_chunks(meta, segs)
        all_chunks.extend(chunks)
        n_art = len({c.article for c in chunks if c.article})
        report.append({"source": meta.file, "pages": len(pages), "chunks": len(chunks), "articles": n_art})
        print(f"[ingest] {meta.file}: {len(pages)} págs → {len(chunks)} chunks ({n_art} artículos)")
    if not all_chunks:
        raise SystemExit("[ingest] No hay documentos para indexar.")
    write_index(all_chunks, index_dir, with_embeddings)
    (index_dir / "ingest_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return all_chunks


if __name__ == "__main__":
    run()
