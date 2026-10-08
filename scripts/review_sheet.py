"""Write native-speaker review sheets: docs/review/<lang>.csv for every key in <lang>.json's _todo_review.

Usage:
    python scripts/review_sheet.py            # yo, ha, ig
    python scripts/review_sheet.py yo         # one language

Columns: key, english, draft, reviewer_text (empty), notes. The file is UTF-8 with a BOM so Excel and
Google Sheets show Yorùbá/Hausa/Igbo letters correctly. Read it back with scripts/apply_review.py.
"""

import csv
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
DATA = ROOT / "data"
OUT = ROOT / "docs" / "review"
FACT_SHEET_KEY = "fact_sheet"  # one extra row: the whole data/fact_sheet_<lang>.md while `review: pending`
LANGS = ("yo", "ha", "ig")
COLUMNS = ("key", "english", "draft", "reviewer_text", "notes")
BUTTON_KEYS = {
    "consent_button",
    "decline_button",
    "knew_yes",
    "knew_no",
    "knew_skip",
    "feedback_yes",
    "feedback_no",
}


def placeholders(text: str) -> list[str]:
    return sorted({name for _, name, _, _ in string.Formatter().parse(text) if name})


def note_for(key: str, english: str) -> str:
    notes = []
    if key == "language_name":
        notes.append("The name of this language, written in this language (shown on the first screen).")
    names = placeholders(english)
    if names:
        notes.append(
            "Keep "
            + ", ".join("{" + n + "}" for n in names)
            + " exactly as written; it is filled in by the app."
        )
    if key in BUTTON_KEYS or key.startswith("btn_"):
        notes.append("Button label: keep it short.")
    if key.startswith("seg_"):
        notes.append('Shown after a code, e.g. "11 = <this text>".')
    if "LA 11 A12 GN 01" in english:
        notes.append("Keep the example postcode LA 11 A12 GN 01 exactly as written.")
    if '"' in english:
        notes.append("A quoted button name must match that button's text in your language (btn_* rows).")
    return " ".join(notes)


def split_fact_sheet(text: str) -> tuple[str, str]:
    """(review status, body) of a fact sheet file with `---\nreview: <status>\n---` front matter."""
    _, front, body = text.split("---\n", 2)
    status = front.split("review:", 1)[1].strip()
    return status, body.strip()


def write_sheet(
    lang: str, templates_dir: Path = TEMPLATES, out_dir: Path = OUT, data_dir: Path = DATA
) -> tuple[Path, int]:
    en = json.loads((templates_dir / "en.json").read_text(encoding="utf-8"))
    draft = json.loads((templates_dir / f"{lang}.json").read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{lang}.csv"
    keys = draft["_todo_review"]
    rows = [[key, en[key], draft[key], "", note_for(key, en[key])] for key in keys]

    status, body = split_fact_sheet((data_dir / f"fact_sheet_{lang}.md").read_text(encoding="utf-8"))
    if status == "pending":
        _, en_body = split_fact_sheet((data_dir / "fact_sheet_en.md").read_text(encoding="utf-8"))
        note = (
            "The facts the assistant may use when explaining postcodes. Keep the Markdown (# and - lines), "
            "every code (AA-99-H77-BB-55, LA-11-A12-GN-01) and the date exactly. Add no new facts or numbers."
        )
        rows.append([FACT_SHEET_KEY, en_body, body, "", note])

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return path, len(rows)


def main(argv: list[str]) -> None:
    for lang in argv or LANGS:
        path, rows = write_sheet(lang)
        print(f"{path.relative_to(ROOT)}  {rows} rows")


if __name__ == "__main__":
    main(sys.argv[1:])
