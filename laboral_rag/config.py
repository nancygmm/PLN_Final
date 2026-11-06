"""Configuración central. Todo se lee de variables de entorno (.env); nunca se guardan credenciales en el código."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv es opcional
    pass

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # Rutas
    raw_dir: Path = ROOT / "data" / "raw"
    index_dir: Path = ROOT / "data" / "index"
    sources_manifest: Path = ROOT / "data" / "sources.yaml"
    logs_dir: Path = ROOT / "logs"

    # LLM: extractive | ollama | openai | groq | gemini
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "extractive"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))
    llm_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0")))
    llm_max_calls_per_query: int = field(default_factory=lambda: int(_env("LLM_MAX_CALLS", "3")))

    # Recuperación
    retrieval_mode: str = field(default_factory=lambda: _env("RETRIEVAL_MODE", "hybrid"))  # bm25 | dense | hybrid
    embedding_model: str = field(
        default_factory=lambda: _env(
            "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )
    top_k: int = field(default_factory=lambda: int(_env("TOP_K", "5")))
    rrf_k: int = 60
    # Umbral mínimo de score BM25 normalizado para no abstenerse
    min_evidence_score: float = field(default_factory=lambda: float(_env("MIN_EVIDENCE_SCORE", "0.15")))

    # Guardrails
    max_query_chars: int = 1000


settings = Settings()
