"""Herramienta: calculadora de prestaciones laborales de Guatemala.

Por qué es necesaria (enunciado §5.6): un LLM no es confiable para hacer aritmética de fechas y montos;
la normativa (recuperada por RAG) dice QUÉ corresponde y esta herramienta calcula CUÁNTO, de forma determinista.

Bases legales (verificar contra la versión vigente indexada):
- Aguinaldo: Decreto 76-78. 100 % del salario ordinario mensual por año completo (1 dic – 30 nov), proporcional.
- Bono 14: Decreto 42-92. Un salario ordinario mensual por año completo (1 jul – 30 jun), proporcional.
- Vacaciones: Código de Trabajo, arts. 130 y 133. 15 días hábiles por año continuo; proporcional al terminar la relación.
- Indemnización: Código de Trabajo, art. 82. Un salario por año de servicio continuo, proporcional por fracción,
  sobre el promedio de los últimos 6 meses. Solo aplica a despido sin justa causa.

Es una herramienta de APOYO: los montos son estimaciones y la indemnización siempre requiere revisión humana.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Concepto = Literal["aguinaldo", "bono14", "vacaciones", "indemnizacion"]
TOOL_NAME = "calculadora_prestaciones"


class ToolError(ValueError):
    """Parámetros inválidos o fuera de rango. El agente la captura y responde de forma controlada."""


class PrestacionesInput(BaseModel):
    concepto: Concepto
    salario_mensual: float = Field(gt=0, le=500_000, description="Salario ordinario mensual en quetzales")
    fecha_inicio: date
    fecha_fin: date
    salario_promedio_6m: Optional[float] = Field(default=None, gt=0, le=500_000)
    vacaciones_gozadas_dias: float = Field(default=0, ge=0, le=365)
    incluir_sextas: bool = True  # sextas partes de aguinaldo y bono 14 en la base de indemnización

    @model_validator(mode="after")
    def _fechas(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("fecha_fin es anterior a fecha_inicio")
        if (self.fecha_fin - self.fecha_inicio).days > 365 * 60:
            raise ValueError("relación laboral de más de 60 años: revise las fechas")
        if self.fecha_inicio.year < 1950:
            raise ValueError("fecha_inicio fuera de rango")
        return self


class PrestacionesOutput(BaseModel):
    concepto: Concepto
    monto: float
    dias_computados: int
    formula: str
    base_legal: str
    needs_human_review: bool
    advertencias: list[str] = Field(default_factory=list)


def _dias(a: date, b: date) -> int:
    return (b - a).days + 1  # ambos extremos incluidos


def _periodo(fin: date, mes_inicio: int, dia_inicio: int) -> date:
    """Inicio del período de cómputo vigente que contiene a 'fin'."""
    inicio = date(fin.year, mes_inicio, dia_inicio)
    return inicio if inicio <= fin else date(fin.year - 1, mes_inicio, dia_inicio)


def calcular(params: PrestacionesInput | dict) -> PrestacionesOutput:
    try:
        p = params if isinstance(params, PrestacionesInput) else PrestacionesInput(**params)
    except Exception as e:  # pydantic.ValidationError u otros
        raise ToolError(str(e)) from e

    adv: list[str] = []
    if p.concepto == "aguinaldo":
        ini = max(p.fecha_inicio, _periodo(p.fecha_fin, 12, 1))
        d = min(_dias(ini, p.fecha_fin), 365)
        monto = p.salario_mensual * d / 365
        return PrestacionesOutput(concepto="aguinaldo", monto=round(monto, 2), dias_computados=d,
                                  formula=f"{p.salario_mensual:.2f} × {d}/365",
                                  base_legal="Decreto 76-78 (período 1 dic – 30 nov)", needs_human_review=False)

    if p.concepto == "bono14":
        ini = max(p.fecha_inicio, _periodo(p.fecha_fin, 7, 1))
        d = min(_dias(ini, p.fecha_fin), 365)
        monto = p.salario_mensual * d / 365
        return PrestacionesOutput(concepto="bono14", monto=round(monto, 2), dias_computados=d,
                                  formula=f"{p.salario_mensual:.2f} × {d}/365",
                                  base_legal="Decreto 42-92 (período 1 jul – 30 jun)", needs_human_review=False)

    if p.concepto == "vacaciones":
        d = _dias(p.fecha_inicio, p.fecha_fin)
        dias_derecho = 15 * d / 365
        pendientes = max(dias_derecho - p.vacaciones_gozadas_dias, 0)
        monto = p.salario_mensual / 30 * pendientes
        adv.append("Estimación: usa salario diario = mensual/30 y no descuenta períodos ya prescritos (art. 136).")
        return PrestacionesOutput(concepto="vacaciones", monto=round(monto, 2), dias_computados=d,
                                  formula=f"({p.salario_mensual:.2f}/30) × (15 × {d}/365 − {p.vacaciones_gozadas_dias})",
                                  base_legal="Código de Trabajo arts. 130 y 133", needs_human_review=False,
                                  advertencias=adv)

    # indemnización
    d = _dias(p.fecha_inicio, p.fecha_fin)
    base = p.salario_promedio_6m or p.salario_mensual
    if p.salario_promedio_6m is None:
        adv.append("No se indicó el promedio de los últimos 6 meses; se usó el salario mensual.")
    if p.incluir_sextas:
        base = base * (1 + 2 / 6)  # base + 1/6 de aguinaldo + 1/6 de bono 14
        adv.append("Incluye sextas partes de aguinaldo y bono 14 en la base; confirmar criterio con RR.HH./asesoría legal.")
    monto = base * d / 365
    adv.append("Solo aplica si el despido fue sin justa causa (art. 82). Requiere revisión humana.")
    return PrestacionesOutput(concepto="indemnizacion", monto=round(monto, 2), dias_computados=d,
                              formula=f"{base:.2f} × {d}/365", base_legal="Código de Trabajo art. 82",
                              needs_human_review=True, advertencias=adv)
