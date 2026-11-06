"""Orquestación con estado (enunciado §6):

Usuario → guardrails de entrada → router de intención → recuperación / herramienta
→ validación de permisos → evidencia → generación estructurada → guardrails de salida → respuesta + traza.

Uso:  python -m laboral_rag.agent "¿Cuántos días de vacaciones me corresponden?" --role colaborador
"""
from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from . import guardrails as G
from . import llm
from .config import settings
from .retrieval import Hit, Retriever
from .schemas import Intent, RAGResponse, SourceRef, UserRole
from .text import strip_accents
from .tools import prestaciones as T

CALC_RE = re.compile(r"\b(calcul\w*|cuanto\s+(me\s+|le\s+)?(toca|corresponde|pagan|recibo|recibe|seria)|monto\s+de)\b")
CONCEPTS = {
    "aguinaldo": "aguinaldo",
    "bono 14": "bono14", "bono14": "bono14", "bono catorce": "bono14",
    "vacaciones": "vacaciones",
    "indemnizacion": "indemnizacion", "liquidacion": "indemnizacion",
}
LEGAL_QUERY = {
    "aguinaldo": "aguinaldo salario ordinario mensual decreto 76-78",
    "bono14": "bonificacion anual bono 14 decreto 42-92",
    "vacaciones": "vacaciones remuneradas quince dias habiles articulo 130",
    "indemnizacion": "indemnizacion despido injustificado un mes de salario por año articulo 82",
}
# Cada cálculo solo puede citar su base legal (no políticas internas u otras leyes).
LEGAL_SOURCES = {
    "aguinaldo": ["decreto_76_78_aguinaldo.pdf", "codigo_de_trabajo.pdf"],
    "bono14": ["decreto_42_92_bono14.pdf"],
    "vacaciones": ["codigo_de_trabajo.pdf"],
    "indemnizacion": ["codigo_de_trabajo.pdf"],
}


@dataclass
class Trace:
    """Estado compartido de una consulta; se guarda (sanitizado) como registro de auditoría."""

    trace_id: str
    role: str
    query: str
    intent: str = ""
    guard_flags: list[str] = field(default_factory=list)
    retrieved: list[dict] = field(default_factory=list)
    dropped_chunks: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    tokens: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    latency_ms: float = 0.0
    error: str | None = None


# ---------- Router ----------
def route(query: str) -> tuple[Intent, str | None]:
    q = strip_accents(query.lower())
    concept = next((v for k, v in CONCEPTS.items() if k in q), None)
    if concept and CALC_RE.search(q):
        return Intent.calculo, concept
    if not G.in_domain(query):
        return Intent.fuera_dominio, None
    return Intent.consulta, concept


def parse_tool_params(query: str, concept: str) -> tuple[dict, list[str]]:
    """Extrae parámetros de la consulta. Devuelve (params, faltantes)."""
    q = query.replace(",", "")
    params: dict = {"concepto": concept}
    m = re.search(r"(?:q\.?\s*|quetzales\s*)(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:quetzales|q\b)", q, re.I)
    if m:
        params["salario_mensual"] = float(m.group(1) or m.group(2))
    dates = []
    for d in re.findall(r"\b(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\b", query):
        fmt = "%d/%m/%Y" if "/" in d else "%Y-%m-%d"
        try:
            dates.append(datetime.strptime(d, fmt).date())
        except ValueError:
            pass
    if len(dates) >= 2:
        params["fecha_inicio"], params["fecha_fin"] = sorted(dates[:2])
    elif len(dates) == 1:
        params["fecha_inicio"], params["fecha_fin"] = dates[0], date.today()
    missing = [k for k in ("salario_mensual", "fecha_inicio") if k not in params]
    return params, missing


class Assistant:
    def __init__(self, retriever: Retriever | None = None, log: bool = True):
        self.retriever = retriever or Retriever()
        self.log = log

    # ---------- API principal ----------
    def ask(self, query: str, role: UserRole | str = UserRole.colaborador) -> tuple[RAGResponse, Trace]:
        role = UserRole(role)
        t0 = time.perf_counter()
        tr = Trace(trace_id=uuid.uuid4().hex[:12], role=role.value, query=query)
        try:
            resp = self._run(query, role, tr)
        except Exception as e:  # degradación controlada: nunca se cae sin respuesta
            tr.error = f"{type(e).__name__}: {e}"
            resp = RAGResponse(answer="Ocurrió un error interno al procesar la consulta. Intente de nuevo o contacte a RR.HH.",
                               abstained=True, needs_human_review=True)
        tr.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if self.log:
            self._write_log(tr, resp)
        return resp, tr

    # ---------- Flujo ----------
    def _run(self, query: str, role: UserRole, tr: Trace) -> RAGResponse:
        g = G.check_input(query)
        tr.guard_flags += g.flags
        if not g.ok:
            tr.intent = "bloqueado"
            tr.guard_flags.append(g.reason)
            return RAGResponse(answer="No puedo procesar esta solicitud. Reformule su pregunta sobre normativa laboral.",
                               abstained=True, needs_human_review=g.reason == "posible_inyeccion")
        query = g.text

        if "accion_critica" in g.flags:
            tr.intent = "accion_critica"
            return RAGResponse(
                answer="Este asistente solo consulta normativa y estima montos; no ejecuta acciones sobre planillas, "
                       "contratos ni expedientes. La solicitud se deriva a un responsable de RR.HH.",
                abstained=True, needs_human_review=True)

        intent, concept = route(query)
        tr.intent = intent.value

        if intent == Intent.fuera_dominio:
            hits = self.retriever.search(query, role, k=3)
            if not hits or hits[0].evidence < 0.5:
                return RAGResponse(answer="La pregunta está fuera del alcance de este asistente (normativa laboral de Guatemala).",
                                   abstained=True)
            intent = Intent.consulta  # el corpus sí la cubre aunque no use vocabulario laboral típico
            tr.intent = intent.value

        if intent == Intent.calculo:
            return self._calculo(query, concept, role, tr)
        return self._consulta(query, role, tr)

    def _retrieve(self, query: str, role: UserRole, tr: Trace, k: int | None = None,
                  sources: list[str] | None = None) -> list[Hit]:
        hits = self.retriever.search(query, role, k=k, source_filter=sources)
        hits, dropped = G.filter_context(hits)
        tr.dropped_chunks += dropped
        if dropped:
            tr.guard_flags.append("contexto_con_instrucciones_descartado")
        tr.retrieved += [{"chunk_id": h.chunk.chunk_id, "rank": h.rank, "score": round(h.score, 4),
                          "evidence": round(h.evidence, 3)} for h in hits]
        return hits

    def _consulta(self, query: str, role: UserRole, tr: Trace) -> RAGResponse:
        hits = self._retrieve(query, role, tr)
        if not hits or hits[0].evidence < settings.min_evidence_score:
            return RAGResponse(answer="No encontré evidencia suficiente en los documentos autorizados para responder.",
                               abstained=True)
        try:
            tr.llm_calls += 1
            out = llm.generate(query, hits)
        except Exception as e:  # el LLM no está disponible → se degrada a la línea base extractiva
            tr.guard_flags.append(f"llm_no_disponible:{type(e).__name__}")
            out = llm._extractive(query, hits)
        for k_, v in out.get("usage", {}).items():
            tr.tokens[k_] = tr.tokens.get(k_, 0) + (v or 0)

        by_id = {h.chunk.chunk_id: h.chunk for h in hits}
        sources = [SourceRef(source=by_id[c].source, page=by_id[c].page, chunk_id=c) for c in out["citations"] if c in by_id]
        invented = [c for c in out["citations"] if c not in by_id]
        resp = RAGResponse(
            answer=out["answer"] or "No encontré evidencia suficiente.",
            sources=sources + [SourceRef(source="?", page=0, chunk_id=c) for c in invented],
            abstained=out["insufficient_evidence"],
            needs_human_review=out["insufficient_evidence"] or hits[0].evidence < 0.3,
        )
        resp, flags = G.check_output(resp, set(by_id))
        tr.guard_flags += flags
        return resp

    def _calculo(self, query: str, concept: str, role: UserRole, tr: Trace) -> RAGResponse:
        params, missing = parse_tool_params(query, concept)
        if missing:
            nombres = {"salario_mensual": "salario mensual (p. ej. Q5,000)", "fecha_inicio": "fecha de inicio (dd/mm/aaaa)"}
            return RAGResponse(answer="Para calcular necesito: " + ", ".join(nombres[m] for m in missing)
                               + ". Opcional: fecha de fin (dd/mm/aaaa).", abstained=True)
        if len(tr.tool_calls) >= 1:  # límite de llamadas a herramientas por consulta
            raise RuntimeError("límite de llamadas a herramientas excedido")
        try:
            res = T.calcular(params)
            tr.tool_calls.append({"tool": T.TOOL_NAME, "params": {k: str(v) for k, v in params.items()}, "ok": True})
        except T.ToolError as e:
            tr.tool_calls.append({"tool": T.TOOL_NAME, "params": {k: str(v) for k, v in params.items()}, "ok": False,
                                  "error": str(e)[:300]})
            return RAGResponse(answer="No pude calcular con esos datos: revise que el salario y las fechas sean válidos "
                               "(salario > 0 y fecha de fin posterior a la de inicio).",
                               abstained=True, tool_used=T.TOOL_NAME, needs_human_review=False)

        legal = [h for h in self._retrieve(LEGAL_QUERY[concept], role, tr, k=2, sources=LEGAL_SOURCES[concept])
                 if h.evidence >= settings.min_evidence_score]
        sources = [SourceRef(source=h.chunk.source, page=h.chunk.page, chunk_id=h.chunk.chunk_id) for h in legal]
        answer = (f"Estimación de {res.concepto}: Q{res.monto:,.2f} ({res.dias_computados} días computados; "
                  f"fórmula: {res.formula}). Base legal: {res.base_legal}.")
        if res.advertencias:
            answer += " Advertencias: " + " ".join(res.advertencias)
        resp = RAGResponse(answer=answer, sources=sources, tool_used=T.TOOL_NAME,
                           needs_human_review=res.needs_human_review or not sources)
        resp, flags = G.check_output(resp, {h.chunk.chunk_id for h in legal}, tool_ran=True)
        tr.guard_flags += flags
        return resp

    # ---------- Auditoría ----------
    def _write_log(self, tr: Trace, resp: RAGResponse) -> None:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        rec = asdict(tr)
        rec["query"] = G.redact(rec["query"])
        rec["response"] = json.loads(resp.model_dump_json())
        rec["response"]["answer"] = G.redact(rec["response"]["answer"])
        rec["ts"] = datetime.now().isoformat(timespec="seconds")
        with (settings.logs_dir / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Asistente laboral GT")
    ap.add_argument("query", nargs="?", help="Pregunta (si se omite, modo interactivo)")
    ap.add_argument("--role", default="colaborador", choices=[r.value for r in UserRole])
    ap.add_argument("--trace", action="store_true", help="Mostrar la traza completa")
    args = ap.parse_args()
    bot = Assistant()

    def show(q: str) -> None:
        resp, tr = bot.ask(q, args.role)
        print(resp.model_dump_json(indent=2))
        if args.trace:
            print(json.dumps(asdict(tr), indent=2, ensure_ascii=False, default=str))

    if args.query:
        show(args.query)
    else:
        while True:
            try:
                q = input("\n> ")
            except (EOFError, KeyboardInterrupt):
                break
            if q.strip():
                show(q)


if __name__ == "__main__":
    main()
