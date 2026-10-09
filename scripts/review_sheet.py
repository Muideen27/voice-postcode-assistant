"""Write native-speaker review sheets: docs/review/<lang>.csv for every key in <lang>.json's _todo_review.

Usage:
    python scripts/review_sheet.py            # yo, ha, ig
    python scripts/review_sheet.py yo         # one language

Three sheets per language: <lang>.csv (conversation strings), faq_<lang>.csv (faq_* answers) and
ui_<lang>.csv (page labels: ui_*, chip, conf_*). Columns: key, english, draft, reviewer_text (empty), notes. The file is UTF-8 with a BOM so Excel and
Google Sheets show Yorùbá/Hausa/Igbo letters correctly. Read it back with scripts/apply_review.py.
"""

import csv
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
OUT = ROOT / "docs" / "review"
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
    if key.startswith("ui_"):
        notes.append("Short label on the web page.")
    if key == "chip":
        notes.append('Shown under the postcode, e.g. "High confidence · 9.2 m away".')
    if key.startswith("faq_"):
        notes.append("Answer to a common question. At most 60 words. Add no new facts, numbers or places.")
    if key == "faq_who_built":
        notes.append("Keep the N-ATLaS sentence in English exactly, and the name 'Nigeria Postcode API'.")
    if key.startswith("seg_"):
        notes.append('Shown after a code, e.g. "11 = <this text>".')
    if "LA 11 A12 GN 01" in english:
        notes.append("Keep the example postcode LA 11 A12 GN 01 exactly as written.")
    if '"' in english:
        notes.append("A quoted button name must match that button's text in your language (btn_* rows).")
    return " ".join(notes)


GROUPS = ("main", "faq", "ui")


def group_of(key: str) -> str:
    if key.startswith("faq_"):
        return "faq"
    if key.startswith(("ui_", "conf_")) or key == "chip":
        return "ui"
    return "main"


def write_sheet(
    lang: str,
    templates_dir: Path = TEMPLATES,
    out_dir: Path = OUT,
    group: str = "main",
) -> tuple[Path, int]:
    """docs/review/<lang>.csv (main), faq_<lang>.csv (faq_* answers) or ui_<lang>.csv (page labels)."""
    en = json.loads((templates_dir / "en.json").read_text(encoding="utf-8"))
    draft = json.loads((templates_dir / f"{lang}.json").read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (f"{lang}.csv" if group == "main" else f"{group}_{lang}.csv")
    keys = [k for k in draft["_todo_review"] if group_of(k) == group]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for key in keys:
            writer.writerow([key, en[key], draft[key], "", note_for(key, en[key])])
    return path, len(keys)


def main(argv: list[str]) -> None:
    for lang in argv or LANGS:
        for group in GROUPS:
            path, rows = write_sheet(lang, group=group)
            print(f"{path.relative_to(ROOT)}  {rows} rows")


if __name__ == "__main__":
    main(sys.argv[1:])
