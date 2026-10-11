"""Judging window: keep the N-ATLaS LLM warm 09:00-17:00 WAT on 15-17 Oct 2026 (LLM only; ASR stays at 0).

PREPARED, NOT ENABLED. Nothing runs until this file is deployed (see CLAUDE.md "Judging window plan"):
    modal deploy deploy/judging_window.py      # enable: crons start firing at the next 09:00 / 17:00 WAT
    modal app stop judging-window              # disable: no more crons
    scripts/warm.sh off                        # and, if stopped mid-window, set the LLM back to 0 now

Cost (Modal list price, 11 Oct 2026): one L4 ≈ $0.80/h × 8 h × 3 days ≈ $19 plus container CPU/memory.
"""

import modal

app = modal.App("judging-window")
image = modal.Image.debian_slim(python_version="3.11")
WAT = "Africa/Lagos"  # West Africa Time, UTC+1, no daylight saving


def set_llm_min(n: int) -> None:
    import json

    settings = modal.Function.from_name("natlas-serve", "serve").update_autoscaler(min_containers=n)
    print(json.dumps({"event": "judging_window", "natlas_min_containers": settings.min_containers}))


@app.function(image=image, schedule=modal.Cron("0 9 15-17 10 *", timezone=WAT), timeout=120)
def llm_warm_on() -> None:
    """09:00 WAT on 15, 16 and 17 Oct: keep one N-ATLaS GPU running."""
    set_llm_min(1)


@app.function(image=image, schedule=modal.Cron("0 17 15-17 10 *", timezone=WAT), timeout=120)
def llm_warm_off() -> None:
    """17:00 WAT on 15, 16 and 17 Oct: back to scale-to-zero."""
    set_llm_min(0)
