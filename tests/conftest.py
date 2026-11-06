from pathlib import Path

import pytest

from laboral_rag.ingest import SourceMeta, build_chunks, clean_pages, extract_pages, segment
from laboral_rag.retrieval import Retriever
from laboral_rag.schemas import UserRole

FIX = Path(__file__).parent / "fixtures"
RAW = Path(__file__).parent.parent / "data" / "raw"
ALL = [UserRole.colaborador, UserRole.rrhh]


def _chunks(path: Path, meta: SourceMeta):
    return build_chunks(meta, segment(clean_pages(extract_pages(path))))


@pytest.fixture(scope="session")
def corpus():
    chunks = _chunks(FIX / "codigo_mini.md", SourceMeta("codigo_mini.md", "Código de Trabajo (fixture)", "test", ALL))
    chunks += _chunks(RAW / "politica_interna_v2026.md",
                      SourceMeta("politica_interna_v2026.md", "Política v2026", "2026-1", [UserRole.rrhh]))
    chunks += _chunks(RAW / "politica_interna_v2024.md",
                      SourceMeta("politica_interna_v2024.md", "Política v2024", "2024-1", [UserRole.rrhh], vigente=False))
    return chunks


@pytest.fixture(scope="session")
def retriever(corpus):
    return Retriever(chunks=corpus, mode="bm25")


@pytest.fixture()
def bot(retriever, monkeypatch):
    from laboral_rag import agent

    return agent.Assistant(retriever, log=False)
