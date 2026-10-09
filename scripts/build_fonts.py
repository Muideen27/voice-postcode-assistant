"""Build the self-hosted, subset woff2 fonts in web/fonts/ (dev only; needs fonttools + brotli).

Usage:
    pip install fonttools==4.66.1 brotli==1.2.0
    python scripts/build_fonts.py            # downloads sources into .font-src/ (git-ignored), writes web/fonts/

Fonts and weights are exactly what web/design/prototype.html loads:
    Atkinson Hyperlegible 400, 700 (body)     Bricolage Grotesque 500-700 + opsz (display)
    JetBrains Mono 700 (codes)
Glyph check (SPEC.md §1): neither Atkinson Hyperlegible (nor its successor Atkinson Hyperlegible Next) nor
Bricolage Grotesque has every Yoruba/Hausa/Igbo letter, so a Noto Sans fallback is built containing ONLY the
missing letters; the CSS adds it with unicode-range. Budget: all fonts < 120 KB (SPEC.md §1).

Size choices (measured 8 Oct 2026):
- Bricolage keeps its variable weight (500-700) and optical size, limited to opsz 12-48: the prototype's
  largest display text is 38 px, so rendering is unchanged and the file drops from 69 to 60 KB.
- JetBrains Mono only renders codes in the phone screen (postcode, segment codes; both weight 700), so only
  the 700 weight is built, subset to ASCII + "·"; no mono fallback is needed. (The prototype's 500 weight
  is used only by its page header, which the app does not ship.)
- pyftsubset's default layout features (kern, liga, mark, mkmk, ccmp, ...) keep accent positioning.
"""

import subprocess
import sys
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".font-src"
OUT = ROOT / "web" / "fonts"

GF = "https://fonts.gstatic.com/s"
GH = "https://github.com/google/fonts/raw/main/ofl"
SOURCES = {
    "atkinson-400.ttf": f"{GF}/atkinsonhyperlegible/v12/9Bt23C1KxNDXMspQ1lPyU89-1h6ONRlW45GE5Q.ttf",
    "atkinson-700.ttf": f"{GF}/atkinsonhyperlegible/v12/9Bt73C1KxNDXMspQ1lPyU89-1h6ONRlW45G8WbcNcw.ttf",
    "bricolage-var.ttf": f"{GH}/bricolagegrotesque/BricolageGrotesque%5Bopsz,wdth,wght%5D.ttf",
    "jetbrains-var.ttf": f"{GH}/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
    "noto-sans-var.ttf": f"{GH}/notosans/NotoSans%5Bwdth,wght%5D.ttf",
}

# Latin (Basic + Latin-1), Latin Extended Additional, the Hausa/Yoruba/Igbo letters outside those blocks,
# combining accents (grave, acute, circumflex, tilde, macron, breve, dot above, diaeresis, caron, dot below)
# and the punctuation the page uses.
LATIN = (
    "U+0020-007E,U+00A0-00FF,U+0143-0144,U+0181,U+018A,U+0198-0199,U+01B3-01B4,U+0253,U+0257,"
    "U+0300-0308,U+030C,U+0323,U+1E00-1EFF,U+2013-2014,U+2018-2019,U+201C-201D,U+2022,U+2026,U+20A6"
)
# Letters missing from each primary font (checked with fontTools, 8 Oct 2026), plus the combining marks
# so a base letter and its accent come from the same font.
MISSING_BODY = (
    "U+1EB8-1EB9,U+1ECC-1ECD,U+1E62-1E63,U+0181,U+0253,U+018A,U+0257,U+0198-0199,U+01B3-01B4,"
    "U+1ECA-1ECB,U+1EE4-1EE5,U+1E44-1E45,U+0300-0301,U+0323"
)
# The display font (Bricolage) misses a subset of these (ṣ ɓ ɗ ƙ ƴ ṅ and capitals); the same file serves both.
CODES = "U+0020-007E,U+00B7"  # JetBrains Mono: postcodes and the format line only


def fetch() -> None:
    SRC.mkdir(exist_ok=True)
    for name, url in SOURCES.items():
        target = SRC / name
        if not target.exists():
            print("download", name)
            urllib.request.urlretrieve(url, target)


def instance(src: str, out: str, **axes: object) -> Path:
    """Pin or limit variation axes, e.g. wght=500 (static) or wght=(500, 700) (range kept)."""
    font = instancer.instantiateVariableFont(TTFont(SRC / src), axes)
    path = SRC / out
    font.save(path)
    return path


def subset(src: Path, out: str, unicodes: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable, "-m", "fontTools.subset", str(src),
            f"--unicodes={unicodes}", "--flavor=woff2",
            "--no-hinting", "--desubroutinize", f"--output-file={OUT / out}",
        ],
        check=True,
    )  # fmt: skip


def main() -> None:
    fetch()
    subset(SRC / "atkinson-400.ttf", "atkinson-400.woff2", LATIN)
    subset(SRC / "atkinson-700.ttf", "atkinson-700.woff2", LATIN)
    bricolage = instance("bricolage-var.ttf", "bricolage-sub.ttf", wdth=100, wght=(500, 700), opsz=(12, 48))
    subset(bricolage, "bricolage.woff2", LATIN)
    subset(instance("jetbrains-var.ttf", "jetbrains-700.ttf", wght=700), "jetbrains-700.woff2", CODES)
    # Fallback: only the missing letters, weight range 400-700 kept (one small file for body and display).
    noto = instance("noto-sans-var.ttf", "noto-sans-400-700.ttf", wdth=100, wght=(400, 700))
    subset(noto, "fallback-sans.woff2", MISSING_BODY)

    total = 0
    for path in sorted(OUT.glob("*.woff2")):
        size = path.stat().st_size
        total += size
        print(f"{path.relative_to(ROOT)}  {size / 1024:.1f} KB")
    print(f"total {total / 1024:.1f} KB (budget 120 KB)")


if __name__ == "__main__":
    main()
