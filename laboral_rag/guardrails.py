from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .config import settings
from .schemas import RAGResponse
from .text import strip_accents

INJECTION_PATTERNS = [
    r"ignora(r)?\s+(todas?\s+)?(las\s+|tus\s+)?(instrucciones|reglas|indicaciones)",
    r"olvida(r)?\s+(todo|tus\s+instrucciones|lo\s+anterior)",
    r"ignore\s+(all\s+|previous\s+|the\s+above\s+)",
    r"(system|sistema)\s*prompt",
    r"(revela|muestra|imprime|dime)\s+(tu|tus|el)\s+(prompt|instrucciones|configuracion)",
    r"actua\s+como\s+(si|un|una)",
    r"modo\s+(desarrollador|developer|dan)",
    r"\bjailbreak\b",
    r"a\s+partir\s+de\s+ahora\s+(eres|seras|responde)",
    r"(soy|como)\s+(el\s+)?(administrador|admin|gerente\s+de\s+rrhh)\b.*(dame|muestra|acceso)",
]
_INJ = [re.compile(p) for p in INJECTION_PATTERNS]

CRITICAL_ACTIONS = re.compile(
    r"\b(despide|despedir|registra|registrar|aprueba|aprobar|envia|enviar|modifica|modificar|borra|borrar|"
    r"elimina|eliminar|paga|pagar|ejecuta|ejecutar)\b.*\b(planilla|empleado|colaborador|pago|liquidacion|"
    r"despido|contrato|registro|expediente)",
)

_INTERROGATIVE = re.compile(r"[¿?]|\b(cuales?|cuantos?|cuanta|cuantas|que|cuanto|como|cuando|donde|por\s*que)\b")
_RECORD_ID = re.compile(r"\b\d{3,}\b")  


def _is_execution_order(query: str) -> bool:
    q = _norm(query)
    if _RECORD_ID.search(q):  
        return True
    return not _INTERROGATIVE.search(q)  

DOMAIN_TERMS = set(
    """trabajo trabajador trabajadora empleado empleada colaborador patrono empleador salario sueldo aguinaldo bono
    bono14 14 vacaciones indemnizacion despido renuncia contrato jornada horas extra extraordinarias descanso
    licencia permiso maternidad paternidad lactancia prestaciones igss planilla preaviso suspension huelga
    sindicato pacto colectivo reglamento interior codigo articulo decreto ministerio mintrab inspeccion
    laboral liquidacion finiquito periodo prueba asueto feriado septimo menor menores teletrabajo
    acoso disciplina amonestacion politica interna rrhh recursos humanos""".split()
)

PII_PATTERNS = [
    (re.compile(r"\b\d{4}\s?\d{5}\s?\d{4}\b"), "[DPI]"),  
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\+?502[\s-]?)?\d{4}[\s-]?\d{4}\b"), "[TEL]"),
    (re.compile(r"\bnit[:\s]*\d{5,9}-?[\dkK]\b", re.I), "[NIT]"),
]


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""
    flags: list[str] = field(default_factory=list)
    text: str = ""


def _norm(s: str) -> str:
    return strip_accents(s.lower())


def is_injection(text: str) -> bool:
    t = _norm(text)
    return any(p.search(t) for p in _INJ)


def check_input(query: str) -> GuardResult:
    if not isinstance(query, str):
        return GuardResult(False, "entrada_invalida")
    clean = "".join(c for c in query if unicodedata.category(c)[0] != "C" or c in "\n\t").strip()
    if not clean:
        return GuardResult(False, "consulta_vacia")
    if len(clean) > settings.max_query_chars:
        return GuardResult(False, "consulta_demasiado_larga")
    if is_injection(clean):
        return GuardResult(False, "posible_inyeccion", ["prompt_injection"], clean)
    flags = []
    if CRITICAL_ACTIONS.search(_norm(clean)) and _is_execution_order(clean):
        flags.append("accion_critica")
    return GuardResult(True, flags=flags, text=clean)


def in_domain(query: str) -> bool:
    toks = set(re.findall(r"[a-z0-9]+", _norm(query)))
    return bool(toks & DOMAIN_TERMS)


def filter_context(hits: list) -> tuple[list, list[str]]:
    """Descarta chunks recuperados que contienen instrucciones dirigidas al modelo."""
    kept, dropped = [], []
    for h in hits:
        if is_injection(h.chunk.text):
            dropped.append(h.chunk.chunk_id)
        else:
            kept.append(h)
    return kept, dropped


def check_output(resp: RAGResponse, allowed_chunk_ids: set[str], tool_ran: bool = False) -> tuple[RAGResponse, list[str]]:
    flags = []
    valid = [s for s in resp.sources if s.chunk_id in allowed_chunk_ids]
    if len(valid) != len(resp.sources):
        flags.append("citas_inventadas_removidas")
    resp = resp.model_copy(update={"sources": valid})

    if not resp.abstained and not resp.sources and not tool_ran:
        flags.append("respuesta_sin_evidencia")
        resp = resp.model_copy(update={
            "answer": "No encontré evidencia suficiente en los documentos autorizados para responder con seguridad.",
            "abstained": True, "needs_human_review": True,
        })
    if re.search(r"(?i)reglas\s+del\s+sistema|system\s+prompt|eres\s+un\s+asistente\s+que", resp.answer):
        flags.append("posible_fuga_de_prompt")
        resp = resp.model_copy(update={"answer": "No puedo compartir esa información.", "sources": [],
                                       "abstained": True, "needs_human_review": True})
    return resp, flags


# ---------- Logs ----------
def redact(text: str) -> str:
    for pat, repl in PII_PATTERNS:
        text = pat.sub(repl, text)
    return text
