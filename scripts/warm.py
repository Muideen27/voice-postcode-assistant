"""Keep the N-ATLaS LLM and the ASR GPU warm for a pilot session, then return both to scale-to-zero.

Use scripts/warm.sh (it activates nothing; run inside the venv):
    scripts/warm.sh 90        # min_containers=1 on both for 90 minutes, then 0
    scripts/warm.sh off       # set both back to 0 now

Sets min_containers=1 on natlas-serve/serve and on voice-postcode/AsrModel, pings both until they answer and
prints each cold-start time, waits, then sets both to 0. Ctrl+C, kill or an error also reset both to 0.
The deployed default stays min_containers=0.
"""

import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import modal

ROOT = Path(__file__).resolve().parents[1]
NATLAS_URL = os.environ.get("NATLAS_URL", "https://muideen27--natlas-serve-serve.modal.run")


def llm_function():
    return modal.Function.from_name("natlas-serve", "serve")


def asr_object():
    return modal.Cls.from_name("voice-postcode", "AsrModel")()


def set_min(n: int) -> None:
    llm = llm_function().update_autoscaler(min_containers=n)
    asr = asr_object().update_autoscaler(min_containers=n)
    print(
        f"min_containers: natlas-serve/serve={llm.min_containers}  voice-postcode/AsrModel={asr.min_containers}"
    )


def api_key() -> str:
    key = os.environ.get("NATLAS_API_KEY")
    if not key and (ROOT / "natlas_api_key.txt").exists():
        key = (ROOT / "natlas_api_key.txt").read_text().strip()
    if not key:
        sys.exit("NATLAS_API_KEY not set and natlas_api_key.txt missing")
    return key


def ping_llm() -> float:
    start = time.perf_counter()
    headers = {"Authorization": f"Bearer {api_key()}"}
    while True:
        try:
            r = httpx.get(f"{NATLAS_URL}/v1/models", headers=headers, timeout=900, follow_redirects=True)
            if r.status_code == 200:
                return time.perf_counter() - start
        except httpx.HTTPError:
            pass
        time.sleep(5)


def ping_asr() -> float:
    start = time.perf_counter()
    asr_object().ping.remote()  # returns once a container has loaded the four models
    return time.perf_counter() - start


def main(argv: list[str]) -> None:
    if argv and argv[0] == "off":
        set_min(0)
        return
    minutes = int(argv[0]) if argv else 60
    if not 1 <= minutes <= 480:
        sys.exit("minutes must be 1..480")

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # kill -> finally -> reset to 0
    try:
        set_min(1)
        with ThreadPoolExecutor(2) as pool:
            llm, asr = pool.submit(ping_llm), pool.submit(ping_asr)
            print(f"LLM ready after {llm.result():.0f} s (cold start if it was at 0)")
            print(f"ASR ready after {asr.result():.0f} s (cold start if it was at 0)")
        until = time.strftime("%H:%M %Z", time.localtime(time.time() + minutes * 60))
        print(f"warm until {until}; Ctrl+C to stop early")
        time.sleep(minutes * 60)
    except KeyboardInterrupt:
        print("stopping early")
    finally:
        set_min(0)


if __name__ == "__main__":
    main(sys.argv[1:])
