"""Screenshots of every phone screen, live page next to the prototype, at 360 px (docs/ui-compare/).

Two steps (the page server uses the project venv; Playwright can live in any other venv):
    python scripts/ui_screens.py serve                 # project venv: http://127.0.0.1:8765, fake services
    python scripts/ui_screens.py shoot                 # a venv with `pip install playwright`; uses Google Chrome

The server runs the real orchestrator, templates, web channel and web/index.html; only the outside services
are fakes (Postcode API answers LA-11-A12-GN-01 at 9.2 m, intent by keyword, ASR returns a fixed sentence),
so the screens show real layout and real template text without network or GPUs. Nothing is logged to disk.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "ui-compare"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


# ---------------------------------------------------------------- serve (project venv)


def serve() -> None:
    import uvicorn

    from app.channels.web import create_api
    from app.orchestrator import Orchestrator, load_templates
    from app.services.interfaces import IntentResult
    from app.services.postcode import LookupResult, ReverseResult, load_states
    from app.store import MemoryDeclineCounter, MemoryLog, MemorySessionStore

    class Postcode:
        async def reverse(self, lat: float, lng: float) -> ReverseResult:
            return ReverseResult(True, "LA-11-A12-GN-01", "LA 11 A12 GN 01", "high", 9.2)

        async def lookup(self, code: str) -> LookupResult:
            ok = code == "LA-11-A12-GN-01"
            return LookupResult(code, ok, "valid" if ok else "not_found")

    class Intent:
        async def classify(self, text: str, lang: str) -> IntentResult:
            t = text.lower()
            if "what is a postcode" in t:
                return IntentResult("explain_postcode", 0.9, "what_is")
            if "correct" in t:
                return IntentResult("validate_postcode", 0.9)
            return IntentResult("get_my_postcode", 0.9)

    class Reply:
        async def explain(self, question: str, lang: str) -> None:
            return None

    class Asr:
        async def transcribe(self, audio: bytes, lang: str, mime: str | None = None) -> str:
            return "Please, I want to know my house postcode."

    templates = load_templates()
    orchestrator = Orchestrator(
        postcode=Postcode(),
        intent=Intent(),
        reply=Reply(),
        asr=Asr(),
        sessions=MemorySessionStore(),
        log=MemoryLog(),
        declines=MemoryDeclineCounter(),
        states=load_states(),
        templates=templates,
    )
    api = create_api(orchestrator.handle, "ui-screens-salt", ROOT / "web", templates)
    uvicorn.run(api, host="127.0.0.1", port=PORT, log_level="warning")


# ---------------------------------------------------------------- shoot (Playwright)

PAIRS = [  # (name, title, has a prototype counterpart)
    ("01-language", "Language", True),
    ("02-consent", "Welcome and consent (new, prototype parts)", False),
    ("03-knew-before", "Did you know your postcode? (new, prototype parts)", False),
    ("04-home", "Home", True),
    ("05-locating", "Waiting: finding your building", True),
    ("06-result", "Postcode result", True),
    ("07-listening", "Voice: listening", True),
    ("08-ask-location", "Answer: ask for location (after voice)", True),
    ("09-type", "Type instead", True),
    ("10-validation", "Answer: postcode checked", True),
    ("11-ask-code", "Ask for a code: location button + text box (new)", False),
    ("12-faq", "FAQ answer (new: template, no generation)", False),
    ("13-yo-language", "Language screen, Yorùbá browser (glyph check)", False),
    ("14-yo-result", "Postcode result in Yorùbá (glyph check)", False),
    ("15-tab-app", "Tab bar + app tab (deployed page)", True),
    ("16-tab-dashboard", "Pilot dashboard tab (deployed page, real data: empty before PILOT_START)", True),
]


def shoot() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    proto_url = (ROOT / "web" / "design" / "prototype.html").as_uri()
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=args)

        def context(locale: str):
            return browser.new_context(
                viewport={"width": 360, "height": 800},
                locale=locale,
                geolocation={"latitude": 6.6018, "longitude": 3.3515},
                permissions=["geolocation", "microphone"],
            )

        def snap(page, name: str, side: str) -> None:
            page.wait_for_timeout(250)
            page.locator("#screen").screenshot(path=str(OUT / f"{name}-{side}.png"))

        # prototype (only the phone screen element is captured)
        pg = context("en-US").new_page()
        pg.goto(proto_url)
        pg.wait_for_selector("[data-l]")
        snap(pg, "01-language", "prototype")
        pg.click("[data-l=en]")
        snap(pg, "04-home", "prototype")
        pg.click("#b-get")
        snap(pg, "05-locating", "prototype")
        pg.wait_for_selector("#b-copy")
        snap(pg, "06-result", "prototype")
        pg.click("#b-back")
        pg.click("#b-ask")
        pg.click("[data-s='0']")
        snap(pg, "07-listening", "prototype")
        pg.wait_for_selector("#b-get2", timeout=8000)
        snap(pg, "08-ask-location", "prototype")
        pg.click("#b-back")
        pg.click("#b-type")
        snap(pg, "09-type", "prototype")
        pg.fill("#msg", "Is LA-11-A12-GN-01 correct?")
        pg.click("button[type=submit]")
        pg.wait_for_selector(".answer", timeout=8000)
        snap(pg, "10-validation", "prototype")

        # live page
        lv = context("en-US").new_page()
        lv.goto(BASE)
        lv.wait_for_selector("[data-l]")
        snap(lv, "01-language", "live")
        lv.click("[data-l=en]")
        lv.wait_for_selector("#b-yes")
        snap(lv, "02-consent", "live")
        lv.click("#b-yes")
        lv.wait_for_selector("[data-k=yes]")
        snap(lv, "03-knew-before", "live")
        lv.click("[data-k=no]")
        lv.wait_for_selector("#b-get")
        snap(lv, "04-home", "live")
        lv.evaluate(
            "window._fetch = window.fetch; window.fetch = (...a) => new Promise(r => setTimeout(() => r(window._fetch(...a)), 1500))"
        )
        lv.click("#b-get")
        snap(lv, "05-locating", "live")
        lv.wait_for_selector("#b-copy")
        lv.evaluate("window.fetch = window._fetch")
        snap(lv, "06-result", "live")
        lv.click("#b-back")
        lv.click("#b-ask")
        lv.wait_for_selector("#b-stop")
        snap(lv, "07-listening", "live")
        lv.click("#b-stop")
        lv.wait_for_selector("#b-get2")
        snap(lv, "08-ask-location", "live")
        lv.click("#b-back")
        lv.click("#b-type")
        snap(lv, "09-type", "live")
        lv.fill("#msg", "Is LA-11-A12-GN-01 correct?")
        lv.click("button[type=submit]")
        lv.wait_for_selector(".answer")
        snap(lv, "10-validation", "live")
        lv.click("#b-back")
        lv.click("#b-type")
        lv.fill("#msg", "is my code correct")
        lv.click("button[type=submit]")
        lv.wait_for_selector("#chat")
        snap(lv, "11-ask-code", "live")
        lv.fill("#msg", "what is a postcode")
        lv.click("button[type=submit]")
        lv.wait_for_selector("[data-fb]")
        snap(lv, "12-faq", "live")

        yo = context("yo-NG").new_page()
        yo.goto(BASE)
        yo.wait_for_selector("[data-l]")
        snap(yo, "13-yo-language", "live")
        yo.click("[data-l=yo]")
        yo.click("#b-yes")
        yo.click("[data-k=skip]")
        yo.click("#b-get")
        yo.wait_for_selector("#b-copy")
        snap(yo, "14-yo-result", "live")
        browser.close()

    rows = ["| Screen | Prototype | Live (web/index.html) |", "|---|---|---|"]
    for name, title, has_proto in PAIRS:
        proto = f"![{name} prototype]({name}-prototype.png)" if has_proto else "—"
        rows.append(f"| {title} | {proto} | ![{name} live]({name}-live.png) |")
    (OUT / "README.md").write_text(
        "# UI compare: live page vs prototype (360 px)\n\n"
        "Generated by `scripts/ui_screens.py` (live page served with fake services; the prototype shows its own\n"
        "simulated data). Only the phone screen element (`#screen`) is captured on both sides.\n\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(list(OUT.glob('*.png')))} screenshots to {OUT.relative_to(ROOT)}")


def tabs(base: str = "https://muideen27--voice-postcode-web.modal.run") -> None:
    """Full-page 360 px screenshots of both tabs on a running page, next to the prototype's."""
    from playwright.sync_api import sync_playwright

    proto_url = (ROOT / "web" / "design" / "prototype.html").as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        ctx = browser.new_context(viewport={"width": 360, "height": 800}, locale="en-US")
        pg = ctx.new_page()
        pg.goto(proto_url)
        pg.wait_for_selector("[data-l]")
        pg.screenshot(path=str(OUT / "15-tab-app-prototype.png"), full_page=True)
        pg.click("#tab-dashboard")
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(OUT / "16-tab-dashboard-prototype.png"), full_page=True)
        lv = ctx.new_page()
        lv.goto(base)
        lv.wait_for_selector("[data-l]")
        lv.screenshot(path=str(OUT / "15-tab-app-live.png"), full_page=True)
        lv.click("#tab-dashboard")
        lv.wait_for_function("document.getElementById('d-status').textContent !== 'Loading…'", timeout=30000)
        lv.screenshot(path=str(OUT / "16-tab-dashboard-live.png"), full_page=True)
        browser.close()
    print("wrote tab screenshots to", OUT.relative_to(ROOT))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "serve"
    {"serve": serve, "shoot": shoot, "tabs": tabs}[mode](*sys.argv[2:])
