"""Recuperación: léxica (BM25), semántica (embeddings) e híbrida (Reciprocal Rank Fusion).

El control de acceso se aplica ANTES de puntuar: un rol nunca ve chunks que no le corresponden,
así que ni el ranking ni el LLM pueden filtrarlos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from .config import settings
from .schemas import Chunk, UserRole
from .text import tokenize

ARTICLE_Q_RE = re.compile(r"art[ií]culo\s+(\d+(?:\s*bis)?)", re.I)
# Si la consulta pide explícitamente una versión anterior, se incluyen documentos no vigentes.
HISTORIC_RE = re.compile(r"(anterior|derogad|antigu|vieja|previa|versi[oó]n\s+20\d\d|en\s+20[01]\d|en\s+202[0-5])", re.I)


@lru_cache(maxsize=1)
def get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


@dataclass
class Hit:
    chunk: Chunk
    score: float  # score del método usado (RRF en híbrido)
    evidence: float  # 0..1, qué tan respaldada está la consulta por este chunk
    rank: int = 0


def load_chunks(index_dir: Path = settings.index_dir) -> list[Chunk]:
    path = index_dir / "chunks.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Corre primero: python -m laboral_rag.ingest")
    return [Chunk.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class Retriever:
    def __init__(self, chunks: list[Chunk] | None = None, mode: str | None = None, index_dir: Path = settings.index_dir):
        self.chunks = chunks if chunks is not None else load_chunks(index_dir)
        self.mode = mode or settings.retrieval_mode
        self._tokens = [tokenize(c.text) for c in self.chunks]
        self.bm25 = BM25Okapi(self._tokens)
        self.emb = None
        if self.mode in ("dense", "hybrid"):
            emb_path = index_dir / "embeddings.npy"
            try:
                import numpy as np

                if emb_path.exists() and chunks is None:
                    self.emb = np.load(emb_path)
                else:
                    self.emb = get_embedder().encode([c.text for c in self.chunks], normalize_embeddings=True)
            except ImportError:
                print("[retrieval] Sin sentence-transformers: se usa solo BM25.")
                self.mode = "bm25"

    # --- utilidades ---
    def _allowed(self, role: UserRole, include_historic: bool = False) -> list[int]:
        return [i for i, c in enumerate(self.chunks) if role in c.access and (c.vigente or include_historic)]

    def _coverage(self, q_tokens: list[str], idx: int) -> float:
        """Fracción de términos de la consulta presentes en el chunk (señal de evidencia léxica)."""
        if not q_tokens:
            return 0.0
        toks = set(self._tokens[idx])
        return sum(t in toks for t in set(q_tokens)) / len(set(q_tokens))

    def _bm25_rank(self, query: str, allowed: list[int]) -> list[tuple[int, float]]:
        scores = self.bm25.get_scores(tokenize(query))
        # Boost a identificadores exactos: si se pide "artículo 82", ese artículo va primero.
        arts = {re.sub(r"\s+", " ", a).lower() for a in ARTICLE_Q_RE.findall(query)}
        ranked = []
        for i in allowed:
            s = float(scores[i])
            if arts and self.chunks[i].article in arts:
                s += 100.0
            ranked.append((i, s))
        return sorted(ranked, key=lambda x: -x[1])

    def _dense_rank(self, query: str, allowed: list[int]) -> list[tuple[int, float]]:
        import numpy as np

        q = get_embedder().encode([query], normalize_embeddings=True)[0]
        sims = self.emb[allowed] @ q
        order = np.argsort(-sims)
        return [(allowed[j], float(sims[j])) for j in order]

    # --- API ---
    def search(self, query: str, role: UserRole = UserRole.colaborador, k: int | None = None,
               source_filter: list[str] | None = None) -> list[Hit]:
        k = k or settings.top_k
        allowed = self._allowed(role, include_historic=bool(HISTORIC_RE.search(query)))
        if source_filter:
            allowed = [i for i in allowed if self.chunks[i].source in source_filter]
        if not allowed:
            return []
        q_tokens = tokenize(query)

        if self.mode == "bm25":
            ranked = self._bm25_rank(query, allowed)[:k]
            hits = [Hit(self.chunks[i], s, self._coverage(q_tokens, i)) for i, s in ranked if s > 0]
        elif self.mode == "dense":
            ranked = self._dense_rank(query, allowed)[:k]
            hits = [Hit(self.chunks[i], s, max(s, self._coverage(q_tokens, i))) for i, s in ranked]
        else:  # hybrid: Reciprocal Rank Fusion de BM25 + denso
            lex = self._bm25_rank(query, allowed)
            den = self._dense_rank(query, allowed)
            dense_sim = dict(den)
            fused: dict[int, float] = {}
            for ranking in (lex, den):
                for r, (i, _) in enumerate(ranking[:50]):
                    fused[i] = fused.get(i, 0.0) + 1.0 / (settings.rrf_k + r + 1)
            ranked = sorted(fused.items(), key=lambda x: -x[1])[:k]
            hits = [Hit(self.chunks[i], s, max(dense_sim.get(i, 0.0), self._coverage(q_tokens, i))) for i, s in ranked]

        for r, h in enumerate(hits, start=1):
            h.rank = r
        return hits
