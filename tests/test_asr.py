"""ASR CPU-side tests: upload checks, ffmpeg decoding, silence, timeouts. No GPU, no models, no network."""

import asyncio
import io
import shutil
import wave

import numpy as np
import pytest

from app.services.asr import (
    MAX_BYTES,
    MODELS,
    SAMPLE_RATE,
    ModalAsr,
    check_upload,
    decode_to_pcm,
    is_silent,
)
from app.services.interfaces import AsrError

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def wav(seconds: float, amplitude: float = 0.3, rate: int = 44_100, channels: int = 2) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    tone = (amplitude * 32767 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)
    frames = np.repeat(tone, channels) if channels > 1 else tone
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())
    return buf.getvalue()


def run(coro):
    return asyncio.run(coro)


def test_models_are_the_four_official_ones_at_pinned_revisions() -> None:
    assert set(MODELS) == {"en", "yo", "ha", "ig"}
    for repo, sha in MODELS.values():
        assert repo.startswith("NCAIR1/") and len(sha) == 40


@pytest.mark.parametrize(
    ("audio", "mime", "kind"),
    [
        (b"", "audio/webm", "bad_audio"),
        (b"x" * (MAX_BYTES + 1), "audio/webm", "too_long"),
        (b"x", "image/png", "bad_audio"),
    ],
)
def test_upload_checks(audio: bytes, mime: str, kind: str) -> None:
    with pytest.raises(AsrError) as err:
        check_upload(audio, mime)
    assert err.value.kind == kind


@pytest.mark.parametrize("mime", ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg; codecs=opus", None])
def test_upload_accepts_browser_types(mime: str | None) -> None:
    check_upload(b"x", mime)


@needs_ffmpeg
def test_decode_resamples_to_16k_mono() -> None:
    pcm = decode_to_pcm(wav(2.0))
    assert pcm.dtype == np.int16
    assert abs(len(pcm) / SAMPLE_RATE - 2.0) < 0.05
    assert not is_silent(pcm)


@needs_ffmpeg
def test_decode_rejects_long_and_broken_audio() -> None:
    with pytest.raises(AsrError) as err:
        decode_to_pcm(wav(22.0, channels=1, rate=16_000))
    assert err.value.kind == "too_long"
    with pytest.raises(AsrError) as err:
        decode_to_pcm(b"not audio at all")
    assert err.value.kind == "bad_audio"


def test_silence_detection() -> None:
    assert is_silent(np.zeros(SAMPLE_RATE * 2, dtype=np.int16))
    assert is_silent(np.full(SAMPLE_RATE // 10, 9000, dtype=np.int16))  # too short
    assert not is_silent((np.sin(np.arange(SAMPLE_RATE) / 5) * 9000).astype(np.int16))


@needs_ffmpeg
def test_transcribe_sends_pcm_for_the_chosen_language() -> None:
    calls: list[tuple[str, int]] = []

    async def remote(lang: str, pcm: bytes) -> str:
        calls.append((lang, len(pcm)))
        return "  mo fẹ́ mọ\npósíkòdì mi "

    text = run(ModalAsr(remote).transcribe(wav(1.0), "yo", "audio/wav"))
    assert text == "mo fẹ́ mọ pósíkòdì mi"
    assert calls[0][0] == "yo" and abs(calls[0][1] - SAMPLE_RATE * 2) < 400  # int16 = 2 bytes/sample


@needs_ffmpeg
def test_silent_clip_skips_the_gpu() -> None:
    async def remote(lang: str, pcm: bytes) -> str:
        raise AssertionError("GPU must not be called for silence")

    assert run(ModalAsr(remote).transcribe(wav(1.0, amplitude=0.0), "en", "audio/wav")) == ""


@needs_ffmpeg
@pytest.mark.parametrize(
    ("behaviour", "kind"),
    [("slow", "timeout"), ("crash", "unavailable"), ("asr_error", "bad_audio")],
)
def test_remote_failures_map_to_kinds(behaviour: str, kind: str) -> None:
    async def remote(lang: str, pcm: bytes) -> str:
        if behaviour == "slow":
            await asyncio.sleep(1)
        if behaviour == "crash":
            raise RuntimeError("container died")
        if behaviour == "asr_error":
            raise AsrError("bad_audio")
        return "x"

    with pytest.raises(AsrError) as err:
        run(ModalAsr(remote, timeout_s=0.05).transcribe(wav(1.0), "ha", "audio/wav"))
    assert err.value.kind == kind
