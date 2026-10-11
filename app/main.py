"""Modal app: the web page, its API and the orchestrator wiring, plus the ASR GPU class (from asr.py).

    modal serve app/main.py      # dev URL, live reload
    modal deploy app/main.py     # https://muideen27--voice-postcode-web.modal.run

Secrets: `voice-postcode` (POSTCODE_API_KEY, HASH_SALT) and `natlas-api` (NATLAS_API_KEY).
State: sessions and daily decline counts in Modal Dicts; the interaction log on the `voice-postcode-logs`
Volume (one JSONL file per container per day). The LLM runs in the separate `natlas-serve` app.
"""

import json
import os
from pathlib import Path
from typing import Any

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
    # PILOT_START (ISO time, set at deploy: `PILOT_START=2026-10-10T09:00:00+01:00 modal deploy app/main.py`):
    # the dashboard counts only log rows from then on. Unset -> the dashboard shows its empty state.
    .env(
        {
            "NATLAS_URL": NATLAS_URL,
            "EXPLAIN_MODE": "faq",
            "VP_ENV": os.environ.get("VP_ENV", "prod"),
            "PILOT_START": os.environ.get("PILOT_START", ""),
        }
    )
    .add_local_python_source("app", ignore=["**/__pycache__/**"])  # include the JSON templates
    .add_local_dir("data", str(ROOT / "data"))
    .add_local_dir("web", str(ROOT / "web"), ignore=["design/**"])
)

sessions_dict = modal.Dict.from_name("voice-postcode-sessions", create_if_missing=True)
declines_dict = modal.Dict.from_name("voice-postcode-declines", create_if_missing=True)
canary_dict = modal.Dict.from_name("voice-postcode-canary", create_if_missing=True)
logs_volume = modal.Volume.from_name("voice-postcode-logs", create_if_missing=True)
SECRETS = [modal.Secret.from_name("voice-postcode"), modal.Secret.from_name("natlas-api")]


STATS_CACHE_S = 60
_stats_cache: dict[str, Any] = {"at": 0.0, "value": None}


async def pilot_stats() -> dict[str, Any]:
    """Dashboard numbers from the log Volume + Dicts, cached 60 s. Each step has a timeout; on failure the
    last cached value (or the empty state) is returned, so the dashboard never hangs the page."""
    import asyncio
    import time

    from app.stats import compute_stats, load_rows

    if _stats_cache["value"] is not None and time.time() - _stats_cache["at"] < STATS_CACHE_S:
        return _stats_cache["value"]
    start = os.environ.get("PILOT_START") or None
    rows: list[dict[str, Any]] = []
    canary: dict[str, Any] = {}
    try:
        await asyncio.wait_for(logs_volume.reload.aio(), 10)  # see other containers' log commits
    except Exception as exc:
        print(json.dumps({"event": "stats_reload_error", "error": type(exc).__name__}))
    try:
        if start:
            rows, _ = await asyncio.to_thread(
                load_rows, Path("/logs"), start
            )  # top level only: dev/ excluded
        canary = dict([item async for item in canary_dict.items.aio()])
    except Exception as exc:
        print(json.dumps({"event": "stats_error", "error": type(exc).__name__}))
    value = compute_stats(rows, canary, start)
    _stats_cache.update(at=time.time(), value=value)
    return value


async def readiness(llm: Any, asr_ready: Any) -> dict[str, bool]:
    """Both checks in parallel, each capped at 2.5 s."""
    import asyncio

    llm_ok, asr_ok = await asyncio.gather(llm.ready(), asr_ready())
    return {"llm": llm_ok, "asr": asr_ok}


def session_store():
    from app.store import ModalDictSessionStore, TtlSessionStore

    return TtlSessionStore(ModalDictSessionStore(sessions_dict))


# Startup rule: nothing may block serving the page. The canary runs as a background task (15 s cap); GPU
# warm-up only runs from /api/warm, in the background. A cold CPU container on Modal takes 6-14 s
# (measured 10 Oct, with and without a memory snapshot), so one CPU-only web container is always kept
# running: the page loads in ~1 s for every user. The GPUs (LLM, ASR) stay at min_containers=0.
@app.function(
    image=image,
    secrets=SECRETS,
    volumes={"/logs": logs_volume},
    scaledown_window=300,
    timeout=300,
    min_containers=1,  # CPU only; keeps the page instant (see the startup rule above)
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    from app.canary import run_canary
    from app.channels.web import create_api
    from app.orchestrator import Orchestrator, load_templates
    from app.services.asr import ModalAsr, asr_ready, warm_asr
    from app.services.llm import NatlasClient, NatlasExplain, NatlasIntent
    from app.services.postcode import PostcodeClient, load_states
    from app.store import JsonlLog, ModalDictCanaryReader, ModalDictCanaryStore, ModalDictDeclineCounter

    templates = load_templates()
    llm = NatlasClient.from_env()
    postcode = PostcodeClient(os.environ["POSTCODE_API_KEY"])
    canary_store = ModalDictCanaryStore(canary_dict)
    orchestrator = Orchestrator(
        postcode=postcode,
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
        canary=ModalDictCanaryReader(canary_dict),
    )
    return create_api(
        orchestrator.handle,
        os.environ["HASH_SALT"],
        ROOT / "web",
        templates,
        warmers=[llm.warm, warm_asr],
        on_start=[lambda: run_canary(postcode, canary_store)],
        stats=pilot_stats,
        readiness=lambda: readiness(llm, asr_ready),
    )


@app.function(image=image, secrets=SECRETS, schedule=modal.Period(minutes=30), timeout=60)
async def postcode_canary() -> None:
    """Every 30 minutes: is the official Postcode API data there? (also run when a web container starts)"""
    from app.canary import run_canary
    from app.services.postcode import PostcodeClient
    from app.store import ModalDictCanaryStore

    client = PostcodeClient(os.environ["POSTCODE_API_KEY"])
    try:
        await run_canary(client, ModalDictCanaryStore(canary_dict))
    finally:
        await client.aclose()


@app.function(image=image, schedule=modal.Period(minutes=15), timeout=120)
async def sweep_unconsented() -> None:
    """Delete sessions that never answered the consent screen within 30 minutes (SPEC §3.8)."""
    items = [item async for item in sessions_dict.items.aio()]
    removed = await session_store().sweep(items)
    print(json.dumps({"event": "session_sweep", "checked": len(items), "removed": removed}))
