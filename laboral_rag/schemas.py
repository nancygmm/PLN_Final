"""Contratos de datos (Pydantic). La salida final del sistema SIEMPRE se valida contra RAGResponse."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class UserRole(str, Enum):
    """Roles del sistema. Cada documento declara qué roles pueden leerlo."""

    colaborador = "colaborador"  # empleado: solo fuentes públicas
    rrhh = "rrhh"  # analista de RR.HH.: públicas + políticas internas


class Chunk(BaseModel):
    """Fragmento indexado con metadatos mínimos de trazabilidad (enunciado §5.3)."""

    chunk_id: str
    text: str
    source: str  # nombre del archivo de origen
    page: int  # página (1-indexada) donde empieza el fragmento
    version: str
    title: str = ""
    article: Optional[str] = None  # p. ej. "82" para "Artículo 82"
    access: list[UserRole] = Field(default_factory=lambda: [UserRole.colaborador, UserRole.rrhh])
    hash: str = ""
    vigente: bool = True  # False = versión histórica/derogada, solo se usa si se pide explícitamente


class SourceRef(BaseModel):
    source: str
    page: int
    chunk_id: str


class RAGResponse(BaseModel):
    """Formato de salida contractual (enunciado §11)."""

    answer: str
    sources: list[SourceRef] = Field(default_factory=list)
    abstained: bool = False
    tool_used: Optional[str] = None
    needs_human_review: bool = False

    @field_validator("answer")
    @classmethod
    def answer_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("answer no puede estar vacío")
        return v


class Intent(str, Enum):
    consulta = "consulta"  # pregunta sobre la normativa → RAG
    calculo = "calculo"  # cálculo de prestaciones → herramienta
    fuera_dominio = "fuera_dominio"


class EvalCase(BaseModel):
    """Registro del banco de pruebas (enunciado §8)."""

    id: str
    question: str
    expected_behavior: str
    expected_sources: list[str] = Field(default_factory=list)
    expected_pages: list[int] = Field(default_factory=list)
    expected_articles: list[str] = Field(default_factory=list)
    answerable: bool
    risk_level: Literal["bajo", "medio", "alto"]
    category: str = ""
    role: UserRole = UserRole.colaborador
