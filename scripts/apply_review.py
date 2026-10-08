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
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
REVIEW = ROOT / "docs" / "review"


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def apply_review(lang: str, csv_path: Path, templates_dir: Path = TEMPLATES) -> tuple[list[str], list[str]]:
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

    data["_todo_review"] = [k for k in data["_todo_review"] if k not in applied]
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
