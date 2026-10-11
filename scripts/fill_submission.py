"""Fill the {{PLACEHOLDERS}} in docs/submission/*.md from the pilot export -> docs/submission/build/*.md.

Usage (after `python scripts/export_log.py --pull --since <pilot start>`):
    python scripts/fill_submission.py

Data placeholders come from docs/validation/summary.md and docs/validation/interactions.csv (never typed by
hand). Placeholders that only a person can fill (pilot dates, tester recruitment, ...) come from
docs/submission/manual.json; empty values stay as {{NAME}}. Every placeholder still open is listed at the
end, so nothing reaches a PDF unnoticed (build_submission.py also highlights them).
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "docs" / "submission"
BUILD = SUBMISSION / "build"
SUMMARY = ROOT / "docs" / "validation" / "summary.md"
INTERACTIONS = ROOT / "docs" / "validation" / "interactions.csv"
MANUAL = SUBMISSION / "manual.json"
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
LANG_NAMES = {"en": "English", "yo": "Yorùbá", "ha": "Hausa", "ig": "Igbo"}

MEASURES = {  # summary.md row label -> placeholder name(s), split on " / "
    "Interactions (logged turns after consent)": ["N_INTERACTIONS"],
    "Content turns (voice, text, location)": ["N_CONTENT_TURNS"],
    "Unique users (salted hashes)": ["N_USERS"],
    "Feedback yes / no": ["FEEDBACK_YES", "FEEDBACK_NO"],
    "Knew their postcode before: yes / no / skipped or not asked": ["KNEW_YES", "KNEW_NO", "KNEW_SKIPPED"],
    "Declined consent (anonymous count)": ["N_DECLINES"],
    "First / last turn": ["PILOT_FIRST_TURN", "PILOT_LAST_TURN"],
}
SECTIONS = {  # summary.md heading -> table placeholder (and chart placeholder for count tables)
    "### By language": ("TABLE_LANGUAGE", "CHART_LANGUAGE"),
    "### By input type": ("TABLE_INPUT", "CHART_INPUT"),
    "### Intent mix (text and voice turns)": ("TABLE_INTENT", "CHART_INTENT"),
    "### Latency per stage (ms)": ("TABLE_LATENCY", None),
    "### Declines per day": ("TABLE_DECLINES", None),
    "### Postcode API data canary per day": ("TABLE_CANARY", None),
}


def table_after(lines: list[str], heading: str) -> list[str]:
    """The first Markdown table after a heading."""
    try:
        i = lines.index(heading)
    except ValueError:
        return []
    rows: list[str] = []
    for line in lines[i + 1 :]:
        if line.startswith("|"):
            rows.append(line)
        elif rows or line.startswith("#"):
            break
    return rows


def chart(table: list[str]) -> str:
    """Single-series horizontal bars as HTML (print): one hue, values printed beside each bar."""
    rows = []
    for line in table[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[1].isdigit():
            rows.append((LANG_NAMES.get(cells[0], cells[0]), int(cells[1])))
    if not rows:
        return "_No data._"
    top = max(n for _, n in rows) or 1
    bars = "".join(
        f'<div class="b"><span>{label}</span><div class="track"><div class="fill" style="width:{100 * n / top:.0f}%">'
        f'</div></div><span class="n">{n}</span></div>'
        for label, n in rows
    )
    return f'<div class="bars">{bars}</div>'


def recent_table(path: Path) -> str:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))[-10:][::-1]
    out = [
        "| Time | Language | Input | Intent | Postcode | Response | Feedback |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        found = {"True": "Found / valid", "False": "Not found"}.get(r["postcode_found"], "—")
        if (r["api_status"] or "").startswith("auth"):
            found = "Error"
        total = f"{int(r['latency_total_ms']) / 1000:.1f} s" if r["latency_total_ms"] else "—"
        out.append(
            f"| {r['ts'][:16].replace('T', ' ')} | {LANG_NAMES.get(r['lang'], r['lang'] or '—')} | {r['input']} | "
            f"{r['intent'] or '—'} | {found} | {total} | {r['feedback'] or '—'} |"
        )
    return "\n".join(out) if rows else "_No data._"


def data_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not SUMMARY.exists():
        return values
    text = SUMMARY.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 2 and cells[0] in MEASURES:
            for name, value in zip(MEASURES[cells[0]], cells[1].split(" / "), strict=False):
                values[name] = value.strip()
        if len(cells) == 2 and cells[0] == "Turns that reached the Postcode API":
            m = re.match(r"(\d+) \((\d+) with a postcode\)", cells[1])
            if m:
                values["N_POSTCODE_TURNS"], values["N_WITH_POSTCODE"] = m.groups()
    since = re.search(r"rows before (\S+) excluded", text)
    if since:
        values["PILOT_START"] = since.group(1)
    for heading, (table_name, chart_name) in SECTIONS.items():
        table = table_after(lines, heading)
        if table:
            values[table_name] = "\n".join(table)
            if chart_name:
                values[chart_name] = chart(table)
    if INTERACTIONS.exists():
        values["TABLE_RECENT"] = recent_table(INTERACTIONS)
    return values


def main() -> None:
    values = data_values()
    if MANUAL.exists():
        values.update({k: v for k, v in json.loads(MANUAL.read_text(encoding="utf-8")).items() if v})
    BUILD.mkdir(exist_ok=True)
    still_open: dict[str, list[str]] = {}
    for src in sorted(SUBMISSION.glob("0*.md")):
        filled = PLACEHOLDER.sub(
            lambda m: values.get(m.group(1), m.group(0)), src.read_text(encoding="utf-8")
        )
        (BUILD / src.name).write_text(filled, encoding="utf-8")
        missing = sorted(set(PLACEHOLDER.findall(filled)))
        if missing:
            still_open[src.name] = missing
    shown = BUILD.relative_to(ROOT) if BUILD.is_relative_to(ROOT) else BUILD
    print(f"filled {len(values)} values into {shown}/")
    for name, missing in still_open.items():
        print(f"  {name}: still open: {', '.join(missing)}")
    if not SUMMARY.exists():
        print(
            "  (no docs/validation/summary.md yet: run scripts/export_log.py --pull --since <pilot start>)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
