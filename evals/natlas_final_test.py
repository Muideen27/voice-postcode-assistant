"""Live N-ATLaS evals: intent (40 cases), FAQ routing (20 cases) and, for EXPLAIN_MODE=generate only,
free-text explain (12 cases). Uses app/services/prompts.py, llm.py and the orchestrator's resolve_intent
directly, so the evals always test the exact prompts and routing the app uses.

Setup:
    export NATLAS_URL=https://muideen27--natlas-serve-serve.modal.run
    export NATLAS_API_KEY=$(cat natlas_api_key.txt)

Usage:
    python evals/natlas_final_test.py            # health (cold start timing), intent, faq
    python evals/natlas_final_test.py intent
    python evals/natlas_final_test.py faq
    python evals/natlas_final_test.py place      # street / place-name subset
    python evals/natlas_final_test.py explain    # generate mode (off in production)

Writes evals/runs/<UTC timestamp>.json with every input, output, status and latency. Record the summary
in evals/results.md (with the commit), plus your language-correctness judgement for explain answers.
"""

import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.orchestrator import resolve_intent, resolve_route  # noqa: E402
from app.services import prompts  # noqa: E402
from app.services.interfaces import LlmError  # noqa: E402
from app.services.llm import NatlasClient, NatlasIntent, guard  # noqa: E402
from evals.cases import (  # noqa: E402
    EXPLAIN_CASES,
    FAQ_CASES,
    FAQ_EQUIVALENT_INTENTS,
    INTENT_CASES,
    PLACE_NAME_CASES,
)

RUNS = ROOT / "evals" / "runs"


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


async def health(client: NatlasClient) -> dict[str, Any]:
    """Time GET /v1/models: on a scaled-down app this includes the full cold start."""
    start = time.perf_counter()
    response = await client._http.get("/v1/models", timeout=900)  # a cold start can exceed the turn timeout
    return {"status": response.status_code, "seconds": round(time.perf_counter() - start, 1)}


async def run_intent(client: NatlasClient) -> dict[str, Any]:
    service = NatlasIntent(client)
    rows = []
    for lang, cases in INTENT_CASES.items():
        for text, expected in cases:
            start = time.perf_counter()
            result, status = None, "ok"
            try:
                result = await service.classify(text, lang)  # type: ignore[arg-type]
            except LlmError as exc:
                status = exc.kind
            ms = round((time.perf_counter() - start) * 1000)
            routed = resolve_intent(text, result)
            rows.append(
                {
                    "lang": lang,
                    "text": text,
                    "expected": expected,
                    "llm_intent": result.intent if result else None,
                    "faq_id": result.faq_id if result else None,
                    "confidence": result.confidence if result else None,
                    "llm_status": status,
                    "routed_intent": routed,
                    "raw_ok": bool(result) and result.intent == expected,
                    "routed_ok": routed == expected,
                    "ms": ms,
                }
            )
            mark = "PASS" if routed == expected else "FAIL"
            print(
                f"[intent {lang}] {mark} llm={rows[-1]['llm_intent']} routed={routed} want={expected}  {text[:60]}"
            )
    return {"rows": rows, "summary": summarise_intent(rows)}


def summarise_intent(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for lang in [*INTENT_CASES, "all"]:
        subset = [r for r in rows if lang == "all" or r["lang"] == lang]
        out[lang] = {
            "n": len(subset),
            "raw_accuracy": round(sum(r["raw_ok"] for r in subset) / len(subset), 3),
            "routed_accuracy": round(sum(r["routed_ok"] for r in subset) / len(subset), 3),
            "llm_errors": sum(r["llm_status"] != "ok" for r in subset),
        }
    return out


async def run_faq(client: NatlasClient) -> dict[str, Any]:
    service = NatlasIntent(client)
    rows = []
    for lang, cases in FAQ_CASES.items():
        for text, expected in cases:
            start = time.perf_counter()
            result, status = None, "ok"
            try:
                result = await service.classify(text, lang)  # type: ignore[arg-type]
            except LlmError as exc:
                status = exc.kind
            ms = round((time.perf_counter() - start) * 1000)
            routed = resolve_intent(text, result)
            faq_id = result.faq_id if result and routed == "explain_postcode" else None
            ok = faq_id == expected or routed == FAQ_EQUIVALENT_INTENTS.get(expected)
            rows.append(
                {
                    "lang": lang,
                    "text": text,
                    "expected_faq": expected,
                    "llm_intent": result.intent if result else None,
                    "faq_id": result.faq_id if result else None,
                    "routed_intent": routed,
                    "llm_status": status,
                    "ok": ok,
                    "ms": ms,
                }
            )
            print(
                f"[faq {lang}] {'PASS' if ok else 'FAIL'} routed={routed} faq={faq_id} want={expected}  {text[:60]}"
            )
    out: dict[str, Any] = {}
    for lang in [*FAQ_CASES, "all"]:
        subset = [r for r in rows if lang == "all" or r["lang"] == lang]
        out[lang] = {"n": len(subset), "accuracy": round(sum(r["ok"] for r in subset) / len(subset), 3)}
    return {"rows": rows, "summary": out}


async def run_place(client: NatlasClient) -> dict[str, Any]:
    """Street / place-name questions must reach faq_place_name_no (LLM or the street/name rule)."""
    service = NatlasIntent(client)
    rows = []
    for lang, texts in PLACE_NAME_CASES.items():
        for text in texts:
            start = time.perf_counter()
            result, status = None, "ok"
            try:
                result = await service.classify(text, lang)  # type: ignore[arg-type]
            except LlmError as exc:
                status = exc.kind
            ms = round((time.perf_counter() - start) * 1000)
            intent, faq_id = resolve_route(text, result)
            ok = faq_id == "place_name_no"
            via = "llm" if result and result.faq_id == "place_name_no" else "rule" if ok else "-"
            rows.append({"lang": lang, "text": text, "llm_intent": result.intent if result else None,
                         "llm_faq_id": result.faq_id if result else None, "routed": [intent, faq_id],
                         "via": via, "llm_status": status, "ok": ok, "ms": ms})  # fmt: skip
            print(
                f"[place {lang}] {'PASS' if ok else 'FAIL'} via={via} routed={intent}/{faq_id}  {text[:60]}"
            )
    out = {lang: round(sum(r["ok"] for r in rows if lang == "all" or r["lang"] == lang)
                       / sum(1 for r in rows if lang == "all" or r["lang"] == lang), 3)
           for lang in [*PLACE_NAME_CASES, "all"]}  # fmt: skip
    return {"rows": rows, "summary": out}


async def run_explain(client: NatlasClient) -> dict[str, Any]:
    facts = {lang: prompts.load_fact_sheet(lang) for lang in prompts.LANG_NAMES}
    rows = []
    for lang, questions in EXPLAIN_CASES.items():
        for question in questions:
            start = time.perf_counter()
            answer, status, reason = None, "ok", None
            try:
                answer = await client.chat(prompts.explain_payload(question, lang, facts[lang]))  # type: ignore[arg-type]
                reason = guard(answer, facts[lang], lang, question)  # type: ignore[arg-type]
            except LlmError as exc:
                status = exc.kind
            ms = round((time.perf_counter() - start) * 1000)
            rows.append(
                {
                    "lang": lang,
                    "question": question,
                    "answer": answer,
                    "llm_status": status,
                    "guard_reason": reason,
                    "guard_pass": status == "ok" and reason is None,
                    "words": len(answer.split()) if answer else 0,
                    "ms": ms,
                }
            )
            print(
                f"[explain {lang}] guard={'PASS' if rows[-1]['guard_pass'] else reason or status}  {question[:50]}"
            )
            print(f"    {answer}\n")
    passed = sum(r["guard_pass"] for r in rows)
    return {
        "rows": rows,
        "summary": {"n": len(rows), "guard_pass": passed, "guard_pass_rate": round(passed / len(rows), 3)},
    }


def latency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ms = [r["ms"] for r in rows]
    return {
        "n": len(ms),
        "p50_ms": percentile(ms, 50),
        "p95_ms": percentile(ms, 95),
        "max_ms": max(ms) if ms else None,
    }


async def main(mode: str) -> None:
    client = NatlasClient.from_env()
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
    )
    report: dict[str, Any] = {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "dirty": dirty,
    }
    try:
        report["health"] = await health(client)
        print("health:", report["health"])
        if mode in ("all", "intent"):
            report["intent"] = await run_intent(client)
            report["intent_latency"] = latency(report["intent"]["rows"])
        if mode in ("all", "faq"):
            report["faq"] = await run_faq(client)
            report["faq_latency"] = latency(report["faq"]["rows"])
        if mode == "place":
            report["place"] = await run_place(client)
            report["place_latency"] = latency(report["place"]["rows"])
        if mode == "explain":
            report["explain"] = await run_explain(client)
            report["explain_latency"] = latency(report["explain"]["rows"])
    except httpx.HTTPError as exc:
        print("endpoint error:", repr(exc))
        raise
    finally:
        await client.aclose()

    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nSUMMARY")
    for key in ("health", "intent_latency", "faq_latency", "place_latency", "explain_latency"):
        if key in report:
            print(f"  {key}: {report[key]}")
    if "intent" in report:
        for lang, s in report["intent"]["summary"].items():
            print(f"  intent {lang}: {s}")
    if "faq" in report:
        for lang, s in report["faq"]["summary"].items():
            print(f"  faq {lang}: {s}")
    if "place" in report:
        print(f"  place: {report['place']['summary']}")
    if "explain" in report:
        print(f"  explain: {report['explain']['summary']}")
    print(f"  written: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
