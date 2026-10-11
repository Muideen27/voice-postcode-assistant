"""Speech to text with the four official NCAIR1 Whisper models. Contract: SPEC.md §3.3.

Split in two:
- CPU side (`ModalAsr`, runs in the web container): checks size and type, decodes any browser recording
  (WebM/Opus, MP4/AAC, OGG, WAV) to 16 kHz mono PCM with ffmpeg through pipes (audio never touches disk),
  enforces the 20 s limit and skips silent clips before any GPU is used.
- GPU side (`AsrModel`, Modal L4 class): loads all four models once per container at pinned revisions and
  transcribes the PCM for the language the user chose. The language is never guessed.
"""

import asyncio
import json
import subprocess
import time
from collections.abc import Awaitable, Callable
from typing import Any

import modal
import numpy as np

from app.events import Lang
from app.services.interfaces import AsrError

# Pinned revisions (HfApi().model_info(repo).sha, 8 Oct 2026) so a repo update cannot change the pilot.
MODELS: dict[Lang, tuple[str, str]] = {
    "yo": ("NCAIR1/Yoruba-ASR", "d1ae7b8b79c2ccd547d8761effe5057433f3fc7f"),
    "ha": ("NCAIR1/Hausa-ASR", "e635b9eda29060c6114c8f4d8b2d903f5c83a44a"),
    "ig": ("NCAIR1/Igbo-ASR", "180732299d5cba3dc8b289260ac84b7838bb3954"),
    "en": ("NCAIR1/NigerianAccentedEnglish", "3c52c6e6c9ec508014a7b9db6a42b503b8930dff"),
}
SAMPLE_RATE = 16_000
MAX_BYTES = 2_000_000
MAX_SECONDS = 20.0
SILENCE_RMS = 0.004  # float32 RMS below this is treated as no speech
ASR_TIMEOUT_S = 20.0  # per turn; a cold GPU (model load) exceeds this -> "timeout" -> retry message
ALLOWED_TYPES = ("audio/webm", "video/webm", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/aac", "audio/wav",
                 "audio/x-wav", "audio/wave", "audio/mpeg")  # fmt: skip


# ---------------------------------------------------------------- CPU side (no models)


def check_upload(audio: bytes, mime: str | None) -> None:
    if not audio:
        raise AsrError("bad_audio", "empty upload")
    if len(audio) > MAX_BYTES:
        raise AsrError("too_long", f"{len(audio)} bytes")
    base = (mime or "").split(";", 1)[0].strip().lower()
    if base and base not in ALLOWED_TYPES:
        raise AsrError("bad_audio", f"type {base}")


def decode_to_pcm(audio: bytes) -> np.ndarray:
    """Any browser recording -> 16 kHz mono int16, via ffmpeg pipes. Reads a little past the limit so an
    over-long clip is detected instead of silently cut."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-t", str(MAX_SECONDS + 1),
           "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"]  # fmt: skip
    try:
        done = subprocess.run(cmd, input=audio, capture_output=True, timeout=15, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AsrError("bad_audio", "ffmpeg timeout") from exc
    if done.returncode != 0 or not done.stdout:
        raise AsrError("bad_audio", done.stderr.decode(errors="replace")[:120])
    pcm = np.frombuffer(done.stdout, dtype=np.int16)
    if len(pcm) / SAMPLE_RATE > MAX_SECONDS:
        raise AsrError("too_long", f"{len(pcm) / SAMPLE_RATE:.1f} s")
    return pcm


def is_silent(pcm: np.ndarray) -> bool:
    if len(pcm) < SAMPLE_RATE // 4:  # under 0.25 s
        return True
    samples = pcm.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples**2))) < SILENCE_RMS


RemoteTranscribe = Callable[[Lang, bytes], Awaitable[str]]


class ModalAsr:
    """AsrService used by the orchestrator. `remote` defaults to the deployed GPU class."""

    def __init__(self, remote: RemoteTranscribe | None = None, timeout_s: float = ASR_TIMEOUT_S) -> None:
        self._remote = remote or _default_remote
        self._timeout_s = timeout_s

    async def transcribe(self, audio: bytes, lang: Lang, mime: str | None = None) -> str:
        check_upload(audio, mime)
        pcm = await asyncio.to_thread(decode_to_pcm, audio)
        if is_silent(pcm):
            return ""  # the orchestrator replies "couldn't hear that clearly"
        try:
            text = await asyncio.wait_for(self._remote(lang, pcm.tobytes()), self._timeout_s)
        except TimeoutError as exc:
            raise AsrError("timeout", f"> {self._timeout_s:.0f} s") from exc
        except AsrError:
            raise
        except Exception as exc:
            raise AsrError("unavailable", type(exc).__name__) from exc
        return " ".join(text.split())


async def _default_remote(lang: Lang, pcm: bytes) -> str:
    return await AsrModel().transcribe.remote.aio(lang, pcm)


async def warm_asr() -> None:
    """Start an ASR GPU container in the background (used by /api/warm). Best effort, not awaited by users."""
    try:
        await AsrModel().ping.spawn.aio()
    except Exception as exc:
        print(json.dumps({"event": "asr_warm_error", "error": type(exc).__name__}))


async def asr_ready(timeout_s: float = 2.5) -> bool:
    """True if an ASR container answers ping within timeout_s (models loaded); False while cold."""
    try:
        return bool(await asyncio.wait_for(AsrModel().ping.remote.aio(), timeout_s))
    except Exception:
        return False


# ---------------------------------------------------------------- GPU side (Modal)

asr_app = modal.App("voice-postcode-asr")
hf_cache = modal.Volume.from_name("hf-cache", create_if_missing=True)
asr_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.14.1",
        "transformers==5.18.0",
        "huggingface_hub==1.33.0",
        "accelerate==1.15.0",
        "numpy==2.4.6",  # newest numpy for Python 3.11 (2.5 needs 3.12)
        "httpx==0.28.1",  # app.services.interfaces imports the postcode client
    )
    .env({"HF_HOME": "/cache"})
    .add_local_python_source("app")
)


@asr_app.cls(
    gpu="L4",
    image=asr_image,
    volumes={"/cache": hf_cache},
    secrets=[modal.Secret.from_name("huggingface")],
    scaledown_window=300,
    timeout=120,
)
class AsrModel:
    @modal.enter()
    def load(self) -> None:
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        started = time.perf_counter()
        self.torch = torch
        self.models: dict[str, Any] = {}
        for lang, (repo, sha) in MODELS.items():
            processor = WhisperProcessor.from_pretrained(repo, revision=sha)
            model = WhisperForConditionalGeneration.from_pretrained(
                repo, revision=sha, torch_dtype=torch.float16
            )
            self.models[lang] = (processor, model.to("cuda").eval())
        print(json.dumps({"event": "asr_loaded", "seconds": round(time.perf_counter() - started, 1)}))

    @modal.method()
    def ping(self) -> bool:
        return True

    @modal.method()
    def transcribe(self, lang: str, pcm: bytes) -> str:
        processor, model = self.models[lang]
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        features = processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
        with self.torch.no_grad():
            ids = model.generate(features.to("cuda", dtype=self.torch.float16), max_new_tokens=128)
        return processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
