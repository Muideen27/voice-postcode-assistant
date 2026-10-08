"""Interfaces the orchestrator depends on. Real implementations: llm.py, asr.py, postcode.py; tests use fakes."""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.events import Lang
from app.services.postcode import LookupResult, ReverseResult

Intent = Literal["get_my_postcode", "validate_postcode", "explain_postcode", "greeting", "other"]
AsrErrorKind = Literal["too_long", "bad_audio", "timeout", "unavailable"]


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    confidence: float | None = None  # below prompts.LOW_CONFIDENCE the orchestrator treats it as "other"
    faq_id: str | None = None  # one of prompts.FAQ_IDS when intent is explain_postcode, else None
    places_mentioned: tuple[str, ...] = ()  # logged for analysis only; never used as a fact


class AsrError(Exception):
    """An ASR failure the orchestrator turns into a localised message. `kind` picks the message."""

    def __init__(self, kind: AsrErrorKind, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


class LlmError(Exception):
    """An LLM call that produced nothing usable. `kind` is logged as llm_status."""

    def __init__(self, kind: Literal["timeout", "error", "bad_json"], detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


class IntentService(Protocol):
    async def classify(self, text: str, lang: Lang) -> IntentResult: ...


class ReplyService(Protocol):
    async def explain(self, question: str, lang: Lang) -> str | None:
        """Grounded answer from the fact sheet, or None when the guard rejects the model output."""
        ...


class AsrService(Protocol):
    async def transcribe(self, audio: bytes, lang: Lang, mime: str | None = None) -> str: ...


class PostcodeService(Protocol):
    async def reverse(self, lat: float, lng: float) -> ReverseResult: ...
    async def lookup(self, code: str) -> LookupResult: ...
