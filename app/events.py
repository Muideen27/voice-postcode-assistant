"""Event (channel -> orchestrator) and Reply (orchestrator -> channel). Contract: SPEC.md §3.1-3.2."""

from dataclasses import dataclass
from typing import Literal

Lang = Literal["en", "yo", "ha", "ig"]
LANGS: tuple[Lang, ...] = ("en", "yo", "ha", "ig")

EventType = Literal["text", "voice", "location", "choice", "feedback"]
ReplyKind = Literal[
    "menu",
    "language_menu",
    "postcode",
    "validation",
    "answer",
    "ask_location",
    "ask_knew_before",
    "error",
    "thanks",
]
Confidence = Literal["high", "medium", "low"]


@dataclass
class Event:
    user_hash: str  # sha256(HASH_SALT + "web:" + session id)
    channel: Literal["web"]  # only "web" for now; see Future work in CLAUDE.md
    type: EventType
    lang: Lang | None
    text: str | None = None  # typed text or menu digit
    audio: bytes | None = None  # raw upload, any of webm/mp4/ogg/wav
    audio_mime: str | None = None
    lat: float | None = None  # never persisted
    lng: float | None = None

    def __repr__(self) -> str:
        # Keep coordinates and audio out of logs and tracebacks.
        return (
            f"Event(user_hash={self.user_hash[:8]}…, channel={self.channel}, type={self.type}, "
            f"lang={self.lang}, text={self.text!r}, audio={len(self.audio or b'')}B, "
            f"has_location={self.lat is not None})"
        )


@dataclass
class Reply:
    kind: ReplyKind
    lang: str
    text: str  # final localised text, ≤ 600 chars
    postcode: str | None = None  # "LA-11-A12-GN-01"
    segments: list[tuple[str, str]] | None = None  # [("LA", "Lagos State"), ...] labels from templates
    confidence: Confidence | None = None
    transcript: str | None = None  # shown to user as "We heard: ..."
