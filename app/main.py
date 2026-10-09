"""Modal app: the web page, its API and the orchestrator wiring, plus the ASR GPU class (from asr.py).

    modal serve app/main.py      # dev URL, live reload
    modal deploy app/main.py     # https://muideen27--voice-postcode-web.modal.run

Secrets: `voice-postcode` (POSTCODE_API_KEY, HASH_SALT) and `natlas-api` (NATLAS_API_KEY).
State: sessions and daily decline counts in Modal Dicts; the interaction log on the `voice-postcode-logs`
Volume (one JSONL file per container per day). The LLM runs in the separate `natlas-serve` app.
"""

import os
from pathlib import Path

import modal

from app.services.asr import asr_app

APP_NAME = "voice-postcode"
NATLAS_URL = "https://muideen27--natlas-serve-serve.modal.run"
ROOT = Path("/root")

app = modal.App(APP_NAME)
app.include(asr_app)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "fastapi[standard]==0.142.4",
        "pydantic==2.13.5",
        "httpx==0.28.1",
        "python-multipart==0.0.32",
        "numpy==2.4.6",  # newest numpy for Python 3.11
    )
    # VP_ENV=dev (set when running `VP_ENV=dev modal serve app/main.py`) sends log rows to /logs/dev/, which
    # export_log.py ignores, so developer test turns never count as pilot evidence.
    .env({"NATLAS_URL": NATLAS_URL, "EXPLAIN_MODE": "faq", "VP_ENV": os.environ.get("VP_ENV", "prod")})
    .add_local_python_source("app", ignore=["**/__pycache__/**"])  # include the JSON templates
    .add_local_dir("data", str(ROOT / "data"))
    .add_local_dir("web", str(ROOT / "web"), ignore=["design/**"])
)

sessions_dict = modal.Dict.from_name("voice-postcode-sessions", create_if_missing=True)
declines_dict = modal.Dict.from_name("voice-postcode-declines", create_if_missing=True)
logs_volume = modal.Volume.from_name("voice-postcode-logs", create_if_missing=True)
SECRETS = [modal.Secret.from_name("voice-postcode"), modal.Secret.from_name("natlas-api")]


def session_store():
    from app.store import ModalDictSessionStore, TtlSessionStore

    return TtlSessionStore(ModalDictSessionStore(sessions_dict))


@app.function(image=image, secrets=SECRETS, volumes={"/logs": logs_volume}, scaledown_window=300, timeout=300)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    from app.channels.web import create_api
    from app.orchestrator import Orchestrator, load_templates
    from app.services.asr import ModalAsr, warm_asr
    from app.services.llm import NatlasClient, NatlasExplain, NatlasIntent
    from app.services.postcode import PostcodeClient, load_states
    from app.store import JsonlLog, ModalDictDeclineCounter

    templates = load_templates()
    llm = NatlasClient.from_env()
    orchestrator = Orchestrator(
        postcode=PostcodeClient(os.environ["POSTCODE_API_KEY"]),
        intent=NatlasIntent(llm),
        reply=NatlasExplain(llm),  # used only when EXPLAIN_MODE=generate
        asr=ModalAsr(),
        sessions=session_store(),
        log=JsonlLog(
            Path("/logs/dev") if os.environ.get("VP_ENV") == "dev" else Path("/logs"),
            suffix=os.environ.get("MODAL_TASK_ID", "local"),
            commit=logs_volume.commit.aio,
        ),
        declines=ModalDictDeclineCounter(declines_dict),
        states=load_states(),
        templates=templates,
        explain_mode="generate" if os.environ.get("EXPLAIN_MODE") == "generate" else "faq",
    )
    return create_api(
        orchestrator.handle,
        os.environ["HASH_SALT"],
        ROOT / "web",
        templates,
        warmers=[llm.warm, warm_asr],
    )


@app.function(image=image, schedule=modal.Period(minutes=15), timeout=120)
async def sweep_unconsented() -> None:
    """Delete sessions that never answered the consent screen within 30 minutes (SPEC §3.8)."""
    import json

    items = [item async for item in sessions_dict.items.aio()]
    removed = await session_store().sweep(items)
    print(json.dumps({"event": "session_sweep", "checked": len(items), "removed": removed}))
