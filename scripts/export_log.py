"""Export the interaction log as validation evidence: docs/validation/interactions.csv + summary.md.

Usage:
    python scripts/export_log.py --pull                         # download log Volume + Dicts, then export
    python scripts/export_log.py --pull --since 2026-10-10T08:00:00+01:00   # pilot turns only
    python scripts/export_log.py --logs path/to/logs [--declines d.json] [--canary c.json]

Rule (SPEC.md §3.8): glob interactions-*.jsonl across all days and containers (top level only: /logs/dev/
holds developer test turns and is ignored), merge, sort by ts, drop duplicates on (ts, user_hash).
Declines and Postcode API canary results come from their Modal Dicts ({"YYYY-MM-DD": ...}).
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.stats import DEFAULT_PILOT_START, load_excluded, load_rows  # noqa: E402  (shared with /api/stats)

EXCLUDED = ROOT / "scripts" / "excluded_hashes.txt"

OUT = ROOT / "docs" / "validation"
CSV_COLUMNS = (
    "ts", "user_hash", "channel", "lang", "input", "transcript", "intent", "llm_status", "postcode_found",
    "api_status", "latency_asr_ms", "latency_llm_ms", "latency_api_ms", "latency_total_ms", "reply_kind",
    "feedback", "knew_postcode_before",
)  # fmt: skip
STAGES = ("asr", "llm", "api", "total")
CANARY = ("valid", "not_found", "auth", "error")


# ---------------------------------------------------------------- load


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    latency = row.get("latency_ms") or {}
    out = {k: row.get(k) for k in CSV_COLUMNS if not k.startswith("latency_")}
    out.update({f"latency_{s}_ms": latency.get(s) for s in STAGES})
    return out


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(flatten(r) for r in rows)


# ---------------------------------------------------------------- summary


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))  # ceil
    return ordered[int(rank) - 1]


def _table(title: str, counts: Counter, total: int | None = None) -> list[str]:
    lines = [f"### {title}", "", "| Value | Count | Share |", "|---|---|---|"]
    total = total if total is not None else sum(counts.values())
    for value, n in counts.most_common():
        share = f"{100 * n / total:.0f}%" if total else "—"
        lines.append(f"| {value if value is not None else '(none)'} | {n} | {share} |")
    return lines + [""]


def summarise(
    rows: list[dict[str, Any]],
    declines: dict[str, int],
    canary: dict[str, dict[str, Any]],
    stats: dict[str, int],
    since: str | None = None,
) -> str:
    users = {r["user_hash"] for r in rows}
    content = [r for r in rows if r.get("input") in ("voice", "text", "location")]
    feedback = Counter(r["feedback"] for r in rows if r.get("feedback"))
    knew = Counter(r["knew_postcode_before"] for r in rows if r.get("knew_postcode_before") is not None)
    knew_users = {r["user_hash"] for r in rows if r.get("knew_postcode_before") is not None}
    found = [r for r in rows if r.get("postcode_found") is not None]
    out = [
        "# Validation summary",
        "",
        f"Source: interaction log, {stats.get('files', 0)} files, {stats.get('lines', 0)} lines "
        f"({stats.get('duplicates', 0)} duplicates and {stats.get('broken', 0)} unreadable lines dropped"
        + (f"; {stats.get('before_since', 0)} rows before {since} excluded" if since else "")
        + (
            f"; {stats.get('excluded', 0)} developer test rows excluded (scripts/excluded_hashes.txt)"
            if stats.get("excluded")
            else ""
        )
        + "). Developer test turns (/logs/dev/) are never included.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Interactions (logged turns after consent) | {len(rows)} |",
        f"| Content turns (voice, text, location) | {len(content)} |",
        f"| Unique users (salted hashes) | {len(users)} |",
        f"| Turns that reached the Postcode API | {len(found)} ({sum(1 for r in found if r['postcode_found'])} with a postcode) |",
        f"| Feedback yes / no | {feedback.get('yes', 0)} / {feedback.get('no', 0)} |",
        f"| Knew their postcode before: yes / no / skipped or not asked | {knew.get(True, 0)} / {knew.get(False, 0)} / {len(users - knew_users)} |",
        f"| Declined consent (anonymous count) | {sum(declines.values())} |",
        f"| First / last turn | {rows[0]['ts'] if rows else '—'} / {rows[-1]['ts'] if rows else '—'} |",
        "",
    ]
    out += _table("By language", Counter(r.get("lang") for r in rows))
    out += _table("By input type", Counter(r.get("input") for r in rows))
    out += _table(
        "Intent mix (text and voice turns)",
        Counter(r.get("intent") for r in content if r.get("input") != "location"),
    )
    out += _table("Reply kinds", Counter(r.get("reply_kind") for r in rows))

    out += ["### Latency per stage (ms)", "", "| Stage | Turns | p50 | p95 |", "|---|---|---|---|"]
    for stage in STAGES:
        values = [r["latency_ms"][stage] for r in rows if (r.get("latency_ms") or {}).get(stage) is not None]
        out.append(
            f"| {stage} | {len(values)} | {percentile(values, 50) or '—'} | {percentile(values, 95) or '—'} |"
        )
    out.append("")

    out += ["### Declines per day", "", "| Date (WAT) | Declines |", "|---|---|"]
    out += [f"| {day} | {n} |" for day, n in sorted(declines.items())] or ["| — | 0 |"]
    out.append("")

    out += [
        "### Postcode API data canary per day",
        "",
        "Lookup of LA-11-A12-GN-01 (level 1) at each web container start and every 30 minutes.",
        "",
        "| Date (WAT) | valid | not_found | auth | error | Last result | Official data available? |",
        "|---|---|---|---|---|---|---|",
    ]
    for day, result in sorted(canary.items()):
        counts = [int(result.get(k, 0)) for k in CANARY]
        available = "yes" if counts[0] else "no (official data returned nothing)" if counts[1] else "unknown"
        out.append(
            f"| {day} | " + " | ".join(map(str, counts)) + f" | {result.get('last', '—')} | {available} |"
        )
    if not canary:
        out.append("| — | | | | | | |")
    return "\n".join(out) + "\n"


def export(
    logs_dir: Path,
    declines: dict[str, int],
    canary: dict[str, dict[str, Any]],
    out_dir: Path = OUT,
    since: str | None = DEFAULT_PILOT_START,
    exclude: set[str] | None = None,
) -> tuple[Path, Path]:
    rows, stats = load_rows(logs_dir, since, exclude)
    csv_path, md_path = out_dir / "interactions.csv", out_dir / "summary.md"
    write_csv(rows, csv_path)
    md_path.write_text(summarise(rows, declines, canary, stats, since), encoding="utf-8")
    return csv_path, md_path


# ---------------------------------------------------------------- pull from Modal


def pull(dest: Path) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    """Download the log Volume into dest and read the declines and canary Dicts."""
    import modal

    subprocess.run(["modal", "volume", "get", "--force", "voice-postcode-logs", "/", str(dest)], check=True)

    def items(name: str) -> dict[str, Any]:
        try:
            return dict(modal.Dict.from_name(name).items())
        except modal.exception.NotFoundError:  # created on first write; none yet means none happened
            return {}

    declines = {k: int(v) for k, v in items("voice-postcode-declines").items()}
    return declines, items("voice-postcode-canary")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pull", action="store_true", help="download logs and counters from Modal first")
    parser.add_argument("--logs", type=Path, help="local folder with interactions-*.jsonl")
    parser.add_argument("--declines", type=Path, help='JSON {"YYYY-MM-DD": count}')
    parser.add_argument("--canary", type=Path, help='JSON {"YYYY-MM-DD": {"valid": n, ...}}')
    parser.add_argument(
        "--since",
        default=DEFAULT_PILOT_START,
        help=f"ISO time; earlier rows are left out (default {DEFAULT_PILOT_START})",
    )
    parser.add_argument(
        "--exclude", type=Path, default=EXCLUDED, help="user hashes of developer test sessions"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    if args.pull:
        with tempfile.TemporaryDirectory() as tmp:
            declines, canary = pull(Path(tmp))
            paths = export(Path(tmp), declines, canary, args.out, args.since, load_excluded(args.exclude))
    else:
        if not args.logs:
            parser.error("--logs or --pull is required")
        declines = json.loads(args.declines.read_text()) if args.declines else {}
        canary = json.loads(args.canary.read_text()) if args.canary else {}
        paths = export(args.logs, declines, canary, args.out, args.since, load_excluded(args.exclude))
    for path in paths:
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


if __name__ == "__main__":
    main(sys.argv[1:])
