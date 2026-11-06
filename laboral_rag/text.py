"""Preprocesamiento de texto: limpieza y tokenización para búsqueda léxica."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

STOPWORDS_ES = set(
    """a al algo algunas algunos ante antes como con contra cual cuando de del desde donde durante e el ella
    ellas ellos en entre era es esa esas ese eso esos esta estas este esto estos fue fueron ha han hasta hay la
    las le les lo los mas me mi mis mucho muy nada ni no nos o otra otras otro otros para pero poco por porque
    que quien se ser si sin sobre su sus tambien tanto te tiene tienen todo todos tu un una uno unos y ya yo
    cuanto cuantos cuanta cuantas cual cuales debe deben puede pueden segun""".split()
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def clean_page_text(text: str) -> str:
    """Normaliza el texto de una página extraída de PDF."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("­", "")  # guion suave
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # palabras cortadas con guion al final de línea
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_repeated_lines(pages: list[str], min_ratio: float = 0.5) -> list[str]:
    """Elimina encabezados/pies de página: líneas que se repiten en más de min_ratio de las páginas,
    y líneas que solo contienen un número de página."""
    if len(pages) < 4:
        return pages
    counts: Counter[str] = Counter()
    for p in pages:
        counts.update({ln.strip() for ln in p.splitlines() if ln.strip()})
    limit = len(pages) * min_ratio
    repeated = {ln for ln, c in counts.items() if c >= limit and len(ln) < 120}
    out = []
    for p in pages:
        keep = [
            ln
            for ln in p.splitlines()
            if ln.strip() not in repeated and not re.fullmatch(r"\s*(p[aá]g(ina)?\.?\s*)?\d{1,4}\s*", ln, re.I)
        ]
        out.append("\n".join(keep))
    return out


def tokenize(text: str) -> list[str]:
    """Tokenización para BM25: minúsculas, sin tildes, sin stopwords. Conserva números
    (importantes para consultas léxicas exactas como 'artículo 82' o 'decreto 42-92')."""
    text = strip_accents(text.lower())
    tokens = re.findall(r"[a-z0-9]+(?:-[0-9]+)?", text)
    return [t for t in tokens if t not in STOPWORDS_ES and (len(t) > 1 or t.isdigit())]
