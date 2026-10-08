"""Apply a filled review sheet back into app/templates/<lang>.json.

Usage:
    python scripts/apply_review.py yo                       # reads docs/review/yo.csv
    python scripts/apply_review.py yo path/to/filled.csv

For every row with a non-empty reviewer_text: checks the {placeholders} match English, writes the text
into <lang>.json and removes the key from _todo_review. Rows with an unknown key or wrong placeholders
are reported and left unchanged. Exit code 1 if any row was rejected. Then run `pytest -q`.
"""

import csv
import json
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
DATA = ROOT / "data"
REVIEW = ROOT / "docs" / "review"
FACT_SHEET_KEY = "fact_sheet"
# Codes, dates and numbers in a fact sheet must survive review unchanged (nothing added, nothing lost).
_TOKEN_RE = re.compile(r"[A-Z]{2}-\d{2}-[A-Z0-9]{3}-[A-Z]{2}-\d{2}|\d+")


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def apply_fact_sheet(lang: str, text: str, data_dir: Path) -> str | None:
    """Write a reviewed fact sheet and mark it done. Returns an error message instead if codes/numbers changed."""
    path = data_dir / f"fact_sheet_{lang}.md"
    draft_body = path.read_text(encoding="utf-8").split("---\n", 2)[2]
    if sorted(_TOKEN_RE.findall(text)) != sorted(_TOKEN_RE.findall(draft_body)):
        return "codes or numbers differ from the draft; keep AA-99-H77-BB-55, LA-11-A12-GN-01 and the date"
    path.write_text(f"---\nreview: done\n---\n{text.strip()}\n", encoding="utf-8")
    return None


def apply_review(
    lang: str, csv_path: Path, templates_dir: Path = TEMPLATES, data_dir: Path = DATA
) -> tuple[list[str], list[str]]:
    """Returns (applied keys, error messages)."""
    en = json.loads((templates_dir / "en.json").read_text(encoding="utf-8"))
    target = templates_dir / f"{lang}.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    applied: list[str] = []
    errors: list[str] = []

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            key = (row.get("key") or "").strip()
            text = (row.get("reviewer_text") or "").strip()
            if not text:
                continue
            if key == FACT_SHEET_KEY:
                error = apply_fact_sheet(lang, text, data_dir)
                if error:
                    errors.append(f"line {line} ({key}): {error}")
                else:
                    applied.append(key)
                continue
            if key.startswith("_") or key not in en or key not in data:
                errors.append(f"line {line}: unknown key {key!r}")
                continue
            try:
                got = placeholders(text)
            except ValueError as exc:  # e.g. a single "{" in the text
                errors.append(f"line {line} ({key}): broken braces: {exc}")
                continue
            if got != placeholders(en[key]):
                want = sorted(placeholders(en[key]))
                errors.append(f"line {line} ({key}): placeholders {sorted(got)} must be {want}")
                continue
            data[key] = text
            applied.append(key)

    data["_todo_review"] = [k for k in data["_todo_review"] if k not in applied]  # fact_sheet is never listed
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return applied, errors


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    lang = argv[0]
    csv_path = Path(argv[1]) if len(argv) > 1 else REVIEW / f"{lang}.csv"
    applied, errors = apply_review(lang, csv_path)
    remaining = json.loads((TEMPLATES / f"{lang}.json").read_text(encoding="utf-8"))["_todo_review"]
    print(f"{lang}: applied {len(applied)}, rejected {len(errors)}, still to review {len(remaining)}")
    for message in errors:
        print("  " + message)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
