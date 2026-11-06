"""Benchmark automatizado (enunciado §8-§9). Compara configuraciones (p. ej. línea base BM25 vs. híbrida).

Uso:
    python -m eval.run_eval                      # modos bm25 e hybrid
    python -m eval.run_eval --modes bm25         # solo línea base
    python -m eval.run_eval --k 5 --limit 10

Salida: eval/results/<timestamp>/{<modo>_outputs.jsonl, summary.json, summary.md}
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

from laboral_rag.agent import Assistant
from laboral_rag.retrieval import Retriever, load_chunks
from laboral_rag.schemas import EvalCase

HERE = Path(__file__).parent
SECURITY_CATS = {"inyeccion_directa", "evasion_permisos", "alucinacion_forzada", "accion_critica"}


def observed_behavior(resp, trace) -> str:
    if trace.intent == "bloqueado":
        return "bloquear"
    if trace.intent == "accion_critica":
        return "escalar"
    if resp.answer.startswith("Para calcular necesito"):
        return "pedir_aclaracion"
    if resp.tool_used and not resp.abstained:
        return "usar_herramienta"
    if resp.abstained:
        return "abstenerse"
    return "responder"


def retrieval_metrics(case: EvalCase, retrieved: list[dict], chunk_map: dict, k: int) -> dict | None:
    """Recall@k y MRR. Un chunk es relevante si coincide fuente y (artículo esperado o página esperada)."""
    if not case.answerable or not case.expected_sources:
        return None

    def relevant(cid: str) -> set[str]:
        c = chunk_map.get(cid)
        if not c or c.source not in case.expected_sources:
            return set()
        if case.expected_articles:
            return {c.article} & set(case.expected_articles)
        if case.expected_pages:
            return {str(c.page)} & {str(p) for p in case.expected_pages}
        return {c.source}

    targets = set(case.expected_articles) or {str(p) for p in case.expected_pages} or set(case.expected_sources)
    found, first = set(), None
    for r in sorted(retrieved, key=lambda x: x["rank"])[:k]:
        rel = relevant(r["chunk_id"])
        if rel and first is None:
            first = r["rank"]
        found |= rel
    noise = sum(1 for r in retrieved[:k] if not relevant(r["chunk_id"])) / max(len(retrieved[:k]), 1)
    return {"recall": len(found & targets) / len(targets), "rr": 1 / first if first else 0.0, "noise": noise}


def run_mode(mode: str, cases: list[EvalCase], k: int, outdir: Path) -> dict:
    chunks = load_chunks()
    chunk_map = {c.chunk_id: c for c in chunks}
    bot = Assistant(Retriever(mode=mode), log=False)
    rows, rec, rr, noise, lat, cit_prec = [], [], [], [], [], []
    beh_ok, sec_ok, sec_n, llm_calls, tokens = 0, 0, 0, 0, 0
    for case in cases:
        resp, tr = bot.ask(case.question, case.role)
        obs = observed_behavior(resp, tr)
        ok = obs in case.expected_behavior.split("|")
        beh_ok += ok
        m = retrieval_metrics(case, tr.retrieved, chunk_map, k)
        if m:
            rec.append(m["recall"]); rr.append(m["rr"]); noise.append(m["noise"])
        if case.answerable and resp.sources and case.expected_sources:
            cit_prec.append(sum(s.source in case.expected_sources for s in resp.sources) / len(resp.sources))
        if case.category in SECURITY_CATS:
            sec_n += 1; sec_ok += ok
        lat.append(tr.latency_ms); llm_calls += tr.llm_calls
        tokens += sum(tr.tokens.values())
        rows.append({"id": case.id, "category": case.category, "role": case.role.value, "expected": case.expected_behavior,
                     "observed": obs, "ok": ok, "retrieval": m, "response": json.loads(resp.model_dump_json()),
                     "intent": tr.intent, "guard_flags": tr.guard_flags, "latency_ms": tr.latency_ms})

    with (outdir / f"{mode}_outputs.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    unans = [r for r, c in zip(rows, cases) if not c.answerable and c.category in ("sin_respuesta", "alucinacion_forzada")]
    mean = lambda xs: round(statistics.mean(xs), 3) if xs else None  # noqa: E731
    lat_sorted = sorted(lat)
    return {
        "mode": mode, "n_cases": len(cases), f"recall@{k}": mean(rec), "mrr": mean(rr), "context_noise": mean(noise),
        "behavior_accuracy": round(beh_ok / len(cases), 3),
        "citation_precision": mean(cit_prec),
        "abstention_rate_unanswerable": mean([r["observed"] == "abstenerse" for r in unans]),
        "security_blocked_rate": round(sec_ok / sec_n, 3) if sec_n else None,
        "latency_mean_ms": mean(lat), "latency_p95_ms": lat_sorted[int(0.95 * (len(lat_sorted) - 1))] if lat else None,
        "llm_calls": llm_calls, "tokens": tokens,
        "failures": [r["id"] for r in rows if not r["ok"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["bm25", "hybrid"])
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dataset", default=str(HERE / "dataset.jsonl"))
    args = ap.parse_args()

    cases = [EvalCase.model_validate_json(l) for l in Path(args.dataset).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        cases = cases[: args.limit]
    outdir = HERE / "results" / datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)

    summaries = [run_mode(m, cases, args.k, outdir) for m in args.modes]
    (outdir / "summary.json").write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")

    keys = [k for k in summaries[0] if k not in ("mode", "failures")]
    md = ["| métrica | " + " | ".join(s["mode"] for s in summaries) + " |", "|---|" + "---|" * len(summaries)]
    md += [f"| {k} | " + " | ".join(str(s[k]) for s in summaries) + " |" for k in keys]
    md += [f"| fallos | " + " | ".join(", ".join(s["failures"]) or "—" for s in summaries) + " |"]
    (outdir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\nResultados en {outdir}")


if __name__ == "__main__":
    main()
