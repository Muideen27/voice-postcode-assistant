"""Interaction-log reading (shared by /api/stats and scripts/export_log.py) and the pilot dashboard numbers.

Real data only: rows come from the interaction log (top-level files only, so /logs/dev/ is never read),
counted from PILOT_START. Nothing returned here contains a transcript or a user hash.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from app.store import WAT, today_wat

LANG_NAMES = {"en": "English", "yo": "Yorùbá", "ha": "Hausa", "ig": "Igbo"}
# Pilot evidence starts here unless PILOT_START (dashboard) or --since (export) says otherwise.
DEFAULT_PILOT_START = "2026-10-11T00:00:00+01:00"
CONTENT_INPUTS = ("voice", "text", "location")


def load_excluded(path: Path) -> set[str]:
    """Developer test sessions to leave out of the evidence: one user hash per line, '#' comments."""
    if not path.exists():
        return set()
    hashes = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            hashes.add(value)
    return hashes


LANG_ORDER = ("yo", "ha", "en", "ig")
ASKED = {
    "get_my_postcode": "My postcode",
    "explain_postcode": "Explain it",
    "validate_postcode": "Check a code",
}


def parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=WAT)


def load_rows(
    logs_dir: Path, since: str | None = None, exclude: set[str] | None = None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """All rows, merged, sorted by ts, deduped on (ts, user_hash). Returns (rows, stats).

    Top-level interactions-*.jsonl only: /logs/dev/ (developer test turns) is never read. `since` is an ISO
    time in any offset; rows before it are dropped. Rows whose user_hash is in `exclude` (developer test
    sessions, scripts/excluded_hashes.txt) are dropped and counted in stats["excluded"].
    """
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    stats = Counter(files=0, lines=0, broken=0, duplicates=0, before_since=0, excluded=0)
    for path in sorted(logs_dir.glob("interactions-*.jsonl")):
        stats["files"] += 1
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            stats["lines"] += 1
            try:
                row = json.loads(line)
                key = (row["ts"], row["user_hash"])
                row["_t"] = parse_ts(row["ts"])
            except (ValueError, KeyError, TypeError):
                stats["broken"] += 1
                continue
            if key in seen:
                stats["duplicates"] += 1
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda r: r["_t"])
    if since:
        start = parse_ts(since)
        kept = [r for r in rows if r["_t"] >= start]
        stats["before_since"] = len(rows) - len(kept)
        rows = kept
    if exclude:
        kept = [r for r in rows if r["user_hash"] not in exclude]
        stats["excluded"] = len(rows) - len(kept)
        rows = kept
    for row in rows:
        row.pop("_t")
    return rows, dict(stats)


def _pct(part: int, whole: int) -> int | None:
    return round(100 * part / whole) if whole else None


def _postcode_outcome(row: dict[str, Any]) -> str:
    status = str(row.get("api_status") or "")
    if row.get("postcode_found") is True:
        return "Valid" if row.get("intent") == "validate_postcode" else "Found"
    if row.get("postcode_found") is False:
        return "Not found"
    if status.startswith(("auth", "unavailable", "timeout", "rate_limited", "credits", "level_not_granted")):
        return "Error"
    return "—"


def _seconds(ms: Any) -> float | None:
    return round(ms / 1000, 1) if isinstance(ms, int | float) else None


def compute_stats(
    rows: list[dict[str, Any]],
    canary: dict[str, dict[str, Any]],
    pilot_start: str | None,
) -> dict[str, Any]:
    """Dashboard numbers. `rows` must already be limited to the pilot (load_rows(since=pilot_start))."""
    content = [r for r in rows if r.get("input") in ("voice", "text", "location")]
    asked_turns = [r for r in content if r.get("input") in ("voice", "text")]
    postcode_turns = [
        r for r in rows if r.get("input") == "location" or r.get("intent") == "validate_postcode"
    ]
    feedback = [r["feedback"] for r in rows if r.get("feedback") in ("yes", "no")]
    knew = [r["knew_postcode_before"] for r in rows if r.get("knew_postcode_before") is not None]

    helped_by_lang = []
    for lang in LANG_ORDER:
        votes = [r["feedback"] for r in rows if r.get("lang") == lang and r.get("feedback") in ("yes", "no")]
        helped_by_lang.append(
            {"label": LANG_NAMES[lang], "pct": _pct(votes.count("yes"), len(votes)), "n": len(votes)}
        )

    asked = Counter(ASKED.get(r.get("intent") or "", "Other") for r in asked_turns)
    medians = {}
    for kind in ("location", "voice"):
        totals = [
            r["latency_ms"]["total"]
            for r in rows
            if r.get("input") == kind and (r.get("latency_ms") or {}).get("total") is not None
        ]
        medians[kind] = _seconds(median(totals)) if totals else None

    today = canary.get(today_wat()) or {}
    last = today.get("last")
    canary_text = {"valid": "OK", "not_found": "no data"}.get(last, "unreachable" if last else "—")

    recent = []
    for r in rows[-10:][::-1]:
        recent.append(
            {
                "time": parse_ts(r["ts"]).astimezone(WAT).strftime("%d %b %H:%M"),
                "language": LANG_NAMES.get(r.get("lang") or "", "—"),
                "input": (r.get("input") or "—").capitalize(),
                "intent": r.get("intent") or "—",
                "postcode": _postcode_outcome(r),
                "latency_s": _seconds((r.get("latency_ms") or {}).get("total")),
                "feedback": {"yes": "Yes", "no": "No"}.get(r.get("feedback") or "", "—"),
            }
        )

    return {
        "pilot_start": pilot_start,
        "kpis": {
            "interactions": len(rows),
            "content_turns": sum(1 for r in rows if r.get("input") in CONTENT_INPUTS),
            "valid_postcode_pct": _pct(
                sum(1 for r in postcode_turns if r.get("postcode_found") is True), len(postcode_turns)
            ),
            "valid_postcode_n": len(postcode_turns),
            "did_not_know_pct": _pct(knew.count(False), len(knew)),
            "did_not_know_n": len(knew),
            "helped_pct": _pct(feedback.count("yes"), len(feedback)),
            "helped_n": len(feedback),
        },
        "by_language": [
            {"label": LANG_NAMES[k], "value": sum(1 for r in rows if r.get("lang") == k)} for k in LANG_ORDER
        ],
        "helped_by_language": helped_by_lang,
        "asked_for": [
            {"label": label, "value": asked.get(label, 0)}
            for label in ("My postcode", "Explain it", "Check a code", "Other")
        ],
        "median_seconds": [
            {"label": "Location", "value": medians["location"]},
            {"label": "Voice", "value": medians["voice"]},
        ],
        "canary_today": canary_text,
        "recent": recent,
    }
