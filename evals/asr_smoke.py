"""Live smoke test of the ASR GPU class on local clips: cold load time, per-clip latency, transcripts.

Usage (from the repo root; runs an ephemeral app, scales to zero afterwards):
    modal run evals/asr_smoke.py --clips yo:yo_test.wav,ha:ha_test.wav,ig:ig_test.wav

Uses the same CPU decoding (ffmpeg) and GPU class as the app, so nothing is copied.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.asr import AsrModel, asr_app, decode_to_pcm, is_silent  # noqa: E402

app = asr_app


@app.local_entrypoint()
def main(clips: str = "yo:yo_test.wav") -> None:
    model = AsrModel()
    for i, item in enumerate(clips.split(",")):
        lang, path = item.split(":", 1)
        pcm = decode_to_pcm(Path(path).read_bytes())
        start = time.perf_counter()
        text = "" if is_silent(pcm) else model.transcribe.remote(lang, pcm.tobytes())
        seconds = time.perf_counter() - start
        label = "cold (includes container start + model load)" if i == 0 else "warm"
        print(f"[{lang}] {len(pcm) / 16000:.1f} s audio, {seconds:.1f} s {label}\n    {text}")
