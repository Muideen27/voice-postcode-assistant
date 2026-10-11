"""Build the submission PDFs: docs/submission/build/*.md (from fill_submission.py) -> docs/submission/*.pdf.

Usage (dev tools: `pip install markdown playwright`; uses the installed Google Chrome):
    python scripts/fill_submission.py
    python scripts/build_submission.py

Markdown -> HTML (tables, code) with Noto Sans (covers ẹ ọ ṣ ɓ ɗ ƙ ƴ ị ụ ṅ and tone marks) -> PDF via headless
Chrome. Unfilled {{PLACEHOLDERS}} are highlighted in yellow so they cannot be missed. After building, the
script extracts the PDF text and checks that every Yorùbá/Hausa/Igbo letter used in the source survives.
"""

import html
import re
import subprocess
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "docs" / "submission"
BUILD = SUBMISSION / "build"
DOCS = ("02_natlas_integration", "03_validation", "04_technical_docs")
SPECIAL = set("ẹọṣɓɗƙƴịụṅẸỌṢƁƊƘƳỊỤṄàáèéìíòóùúńÀÁÈÉÌÍÒÓÙÚ")

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: "Noto Sans", sans-serif; font-size: 10.5pt; line-height: 1.5; color: #15231b; }
h1 { font-size: 20pt; margin: 0 0 6pt; color: #0d7a4c; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1px solid #d3dccf; padding-bottom: 3pt; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; }
a { color: #0d7a4c; }
code, pre { font-family: "Noto Sans Mono", monospace; font-size: 8.5pt; }
pre { background: #eef2ec; border-radius: 6px; padding: 8pt; white-space: pre-wrap; word-break: break-word; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 9pt; page-break-inside: auto; }
th, td { border-bottom: 1px solid #d3dccf; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background: #eef2ec; }
tr { page-break-inside: avoid; }
mark.todo { background: #f6c453; color: #2a1f00; padding: 0 2pt; border-radius: 3px; }
.bars { display: flex; flex-direction: column; gap: 5pt; margin: 6pt 0 10pt; max-width: 120mm; }
.bars .b { display: grid; grid-template-columns: 30mm 1fr 14mm; align-items: center; gap: 6pt; }
.bars .track { height: 9pt; background: #eef2ec; border-radius: 4px; overflow: hidden; }
.bars .fill { height: 100%; background: #0d7a4c; border-radius: 0 4px 4px 0; }
.bars .n { text-align: right; font-family: "Noto Sans Mono", monospace; font-size: 9pt; }
img { max-width: 100%; }
"""


def to_html(md_text: str) -> tuple[str, str]:
    title = "Voice Postcode Assistant"
    match = re.match(r"---\n(.*?)\n---\n", md_text, re.S)
    if match:
        found = re.search(r'title:\s*"?(.*?)"?\s*$', match.group(1), re.M)
        title = found.group(1) if found else title
        md_text = md_text[match.end() :]
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    body = re.sub(r"\{\{([A-Z0-9_]+)\}\}", r'<mark class="todo">{{\1}}</mark>', body)
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<base href="{SUBMISSION.as_uri()}/"><style>{CSS}</style></head><body>{body}</body></html>"""
    return title, doc


def check_glyphs(pdf: Path, source: str) -> list[str]:
    text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    used = {c for c in source if c in SPECIAL}
    return sorted(c for c in used if c not in text)


def main() -> None:
    sources = {
        name: (BUILD / f"{name}.md" if (BUILD / f"{name}.md").exists() else SUBMISSION / f"{name}.md")
        for name in DOCS
    }
    failed = False
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page()
        for name, src in sources.items():
            source = src.read_text(encoding="utf-8")
            _, doc = to_html(source)
            html_path = BUILD / f"{name}.html"
            BUILD.mkdir(exist_ok=True)
            html_path.write_text(doc, encoding="utf-8")
            page.goto(html_path.as_uri())
            page.wait_for_load_state("networkidle")
            pdf = SUBMISSION / f"{name}.pdf"
            page.pdf(path=str(pdf), format="A4", print_background=True, prefer_css_page_size=True)
            missing = check_glyphs(pdf, source)
            todo = len(re.findall(r"\{\{[A-Z0-9_]+\}\}", source))
            status = (
                f"glyphs OK ({len({c for c in source if c in SPECIAL})} special letters)"
                if not missing
                else f"MISSING GLYPHS: {''.join(missing)}"
            )
            failed |= bool(missing)
            print(
                f"{pdf.relative_to(ROOT)}  {pdf.stat().st_size // 1024} KB  from {src.relative_to(ROOT)}  {status}  open placeholders: {todo}"
            )
        browser.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
