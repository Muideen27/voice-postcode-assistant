"""Capture real requests and responses for the submission docs -> docs/submission/examples/*.json.

Usage (GPUs warm first: scripts/warm.sh 10):
    export NATLAS_API_KEY=$(cat natlas_api_key.txt)
    python scripts/capture_examples.py

Runs one real session against the deployed page (Yorùbá voice, English FAQ, location, code check) and one raw
N-ATLaS intent call with the exact payload from app/services/prompts.py. No secrets are written: the session
UUID is replaced by "<session uuid>" and API keys never appear in requests or outputs.
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import prompts  # noqa: E402
from app.services.llm import NatlasClient  # noqa: E402

BASE = "https://muideen27--voice-postcode-web.modal.run"
OUT = ROOT / "docs" / "submission" / "examples"


def redact(obj: object, session: str) -> object:
    return json.loads(json.dumps(obj, ensure_ascii=False).replace(session, "<session uuid>"))


def web_session() -> list[dict]:
    session = str(uuid.uuid4())
    steps = [
        ("Pick language (Yorùbá)", "/api/language", {"session": session, "lang": "yo"}),
        ("Consent", "/api/consent", {"session": session, "agree": True}),
        ("Did you know your postcode? No", "/api/feedback", {"session": session, "knew_before": False}),
        ("Voice note (Yorùbá)", "/api/voice", None),
        (
            "Location (Ikeja test point)",
            "/api/location",
            {"session": session, "lat": 6.6018, "lng": 3.3515, "accuracy_m": 10},
        ),
        ("Typed question", "/api/text", {"session": session, "text": "kí ni pósíkòdì gan-an?"}),
        ("Code check", "/api/text", {"session": session, "text": "ṣé LA-11-A12-GN-01 tọ̀nà?"}),
        ("Feedback", "/api/feedback", {"session": session, "helpful": True}),
    ]
    out = []
    with httpx.Client(base_url=BASE, timeout=120) as http:
        for title, path, body in steps:
            start = time.perf_counter()
            if body is None:
                audio = (ROOT / "yo_test-02.wav").read_bytes()
                r = http.post(
                    path, data={"session": session}, files={"audio": ("note.wav", audio, "audio/wav")}
                )
                request = {"session": session, "audio": f"<yo_test-02.wav, {len(audio)} bytes, audio/wav>"}
            else:
                r = http.post(path, json=body)
                request = body
            out.append(
                {
                    "step": title,
                    "request": {"method": "POST", "path": path, "body": redact(request, session)},
                    "status": r.status_code,
                    "seconds": round(time.perf_counter() - start, 1),
                    "response": redact(r.json(), session),
                }
            )
            print(f"{title}: {r.status_code} {out[-1]['response'].get('kind')}")
    return out


async def natlas_intent() -> dict:
    client = NatlasClient.from_env()
    text, lang = "ki ni itumo posikodi tuntun yi", "yo"
    payload = prompts.intent_payload(text, lang)
    start = time.perf_counter()
    content = await client.chat(payload)
    seconds = round(time.perf_counter() - start, 1)
    await client.aclose()
    shown = dict(payload)
    shown["messages"] = [
        payload["messages"][0],
        {
            "note": f"{len(prompts.INTENT_FEW_SHOT)} few-shot pairs (user/assistant) from prompts.INTENT_FEW_SHOT omitted"
        },
        payload["messages"][-1],
    ]
    return {
        "endpoint": "POST {NATLAS_URL}/v1/chat/completions (Authorization: Bearer <NATLAS_API_KEY>)",
        "request": shown,
        "seconds": seconds,
        "response_content": json.loads(content),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "web_session.json").write_text(json.dumps(web_session(), ensure_ascii=False, indent=2) + "\n")
    (OUT / "natlas_intent.json").write_text(
        json.dumps(asyncio.run(natlas_intent()), ensure_ascii=False, indent=2) + "\n"
    )
    print("written to", OUT.relative_to(ROOT))


if __name__ == "__main__":
    import os

    os.environ.setdefault("NATLAS_URL", "https://muideen27--natlas-serve-serve.modal.run")
    main()
