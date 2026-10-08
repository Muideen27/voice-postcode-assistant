"""Conversation state machine: Event in, Reply out. Contract: CLAUDE.md "Conversation flow", SPEC.md §3.

Stages: new (language menu) -> consent -> knew_before -> ready. Facts (postcodes, validity, state names) come
only from the Postcode API and data/states.json; the LLM only classifies intent and words explanations.
Nothing raises to the channel: every failure becomes a localised template with a next step.
"""

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.events import LANGS, Event, Lang, Reply
from app.privacy import for_storage
from app.services.interfaces import (
    AsrError,
    AsrService,
    Intent,
    IntentService,
    LlmError,
    PostcodeService,
    ReplyService,
)
from app.services.postcode import POSTCODE_RE, PostcodeError, display, find_postcode, normalise, segments
from app.store import (
    DeclineCounter,
    Feedback,
    InputKind,
    InteractionLog,
    Latency,
    LlmStatus,
    LogRow,
    Session,
    SessionStore,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

MENU_ORDER: tuple[Lang, ...] = ("yo", "ha", "ig", "en")  # 1 Yorùbá, 2 Hausa, 3 Igbo, 4 English
LANGUAGE_CHOICES: dict[str, Lang] = {str(i): lang for i, lang in enumerate(MENU_ORDER, 1)} | {
    lang: lang for lang in LANGS
}
AGREE = {"agree", "yes", "1"}
DECLINE = {"decline", "no", "2"}
YES = {"yes", "1"}
NO = {"no", "2"}
SKIP = {"skip", "3"}

# Keyword safety net, matched on lower-cased text with diacritics removed (ASR output often lacks them).
# Checked only when the LLM says "other". Validation words win over postcode words.
_VALIDATE_RE = re.compile(
    r"\b(?:valid|correct|check|real|confirm|tona|sayewo|daidai|ingantacciya|duba|ziri ezi|lelee)\b"
)
_POSTCODE_RE = re.compile(r"\b(?:postcode|post code|posikodi|koodu|lamba|adiresi|address)")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
EXAMPLE_POSTCODE = "LA-11-A12-GN-01"  # the only code the templates and fact sheets use as an example

POSTCODE_ERROR_TEMPLATES = {
    "timeout": "error_slow",
    "rate_limited": "error_slow",
    "unavailable": "error_unavailable",
    "config": "error_generic",
    "credits": "error_generic",
    "level_not_granted": "error_generic",
}
ALERT_KINDS = {"config", "credits", "level_not_granted"}  # our setup is wrong, not the user's input
ASR_ERROR_TEMPLATES = {
    "too_long": "audio_too_long",
    "bad_audio": "not_heard",
    "timeout": "timeout_retry",
    "unavailable": "error_generic",
}
SEGMENT_KEYS = ("seg_lga", "seg_district", "seg_area", "seg_building")


def load_templates(directory: Path = TEMPLATES_DIR) -> dict[Lang, dict[str, str]]:
    """All user-facing strings, per language. Keys starting with "_" are metadata, not strings."""
    out: dict[Lang, dict[str, str]] = {}
    for lang in LANGS:
        data = json.loads((directory / f"{lang}.json").read_text(encoding="utf-8"))
        out[lang] = {k: v for k, v in data.items() if not k.startswith("_")}
    return out


def fold(text: str) -> str:
    """Lower-case and strip diacritics: "Pósíkòdì" -> "posikodi"."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def safety_net(text: str) -> Intent:
    folded = fold(text)
    if _VALIDATE_RE.search(folded):
        return "validate_postcode"
    if _POSTCODE_RE.search(folded):
        return "get_my_postcode"
    return "other"


def log_event(event: str, **fields: Any) -> None:
    """One JSON line per operational event. Never pass coordinates, audio or raw ids here."""
    print(json.dumps({"event": event, **fields}, ensure_ascii=False))


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


@dataclass
class _Turn:
    """Everything the log row needs, collected while one event is handled."""

    input: InputKind
    transcript: str | None = None  # always for_storage(...): scrubbed and capped
    intent: str | None = None
    llm_status: LlmStatus | None = None
    postcode_found: bool | None = None
    api_status: str | None = None
    latency: Latency = field(default_factory=Latency)
    feedback: Feedback | None = None
    knew_postcode_before: bool | None = None
    reply_kind: str | None = None  # overrides Reply.kind in the log (e.g. "template_fallback")


class Orchestrator:
    def __init__(
        self,
        *,
        postcode: PostcodeService,
        intent: IntentService,
        reply: ReplyService,
        asr: AsrService,
        sessions: SessionStore,
        log: InteractionLog,
        declines: DeclineCounter,
        states: dict[str, str],
        templates: dict[Lang, dict[str, str]] | None = None,
    ) -> None:
        self.postcode = postcode
        self.intent = intent
        self.reply = reply
        self.asr = asr
        self.sessions = sessions
        self.log = log
        self.declines = declines
        self.states = states
        self.templates = templates or load_templates()

    # ---------------------------------------------------------------- entry point

    async def handle(self, event: Event) -> Reply:
        started = time.perf_counter()
        turn = _Turn(input=_input_kind(event))
        lang: Lang = event.lang or "en"
        session: Session | None = None
        try:
            session = await self.sessions.get(event.user_hash)
            lang = session.lang or lang
            reply = await self._route(event, session, turn)
            if session.stage == "new":  # no language yet, or declined: nothing about this user is kept
                await self.sessions.delete(event.user_hash)
                if reply.kind == "declined":
                    await self._count_decline()
            else:
                session.turns += 1
                await self.sessions.put(event.user_hash, session)
        except Exception as exc:  # last line of defence: the channel always gets a Reply
            log_event("orchestrator_error", error=type(exc).__name__, detail=str(exc)[:200])
            reply = self._error(session.lang if session and session.lang else lang, "error_generic")
            turn.api_status = turn.api_status or "internal_error"

        turn.latency.total = _ms(started)
        # Log only users who agreed: before consent, and after declining, nothing is written.
        if session is not None and session.stage in ("knew_before", "ready"):
            await self._write_log(event, session, turn, reply)
        return reply

    # ---------------------------------------------------------------- stages

    async def _route(self, event: Event, s: Session, turn: _Turn) -> Reply:
        choice = (event.text or "").strip().lower()
        lang: Lang = s.lang or event.lang or "en"

        if s.stage == "new":  # first screen: language menu; the session is stored only once one is chosen
            chosen = LANGUAGE_CHOICES.get(choice)
            if chosen is None:
                return self._language_menu(lang)
            s.lang = chosen
            s.stage = "consent"
            return self._welcome(chosen)

        if s.stage == "consent":
            if choice in AGREE:
                s.stage = "knew_before"
                return Reply(kind="ask_knew_before", lang=lang, text=self._t(lang, "ask_knew_before"))
            if choice in DECLINE:
                s.stage = "new"
                return Reply(kind="declined", lang=lang, text=self._t(lang, "declined"))
            if choice in LANGS:  # changed their mind about the language
                s.lang = LANGUAGE_CHOICES[choice]
                return self._welcome(s.lang)
            return self._welcome(lang)

        if s.stage == "knew_before":
            if choice in YES | NO | SKIP:
                turn.knew_postcode_before = True if choice in YES else False if choice in NO else None
                s.stage = "ready"
                return self._menu(lang)
            return Reply(kind="ask_knew_before", lang=lang, text=self._t(lang, "ask_knew_before"))

        return await self._ready(event, s, turn, lang, choice)

    async def _ready(self, event: Event, s: Session, turn: _Turn, lang: Lang, choice: str) -> Reply:
        if (
            event.type == "choice" and choice in LANGUAGE_CHOICES
        ):  # language change; never re-asks knew_before
            s.lang = LANGUAGE_CHOICES[choice]
            return self._menu(s.lang)

        typed_feedback = event.type == "text" and s.awaiting_feedback and choice in YES | NO
        if event.type == "feedback" or typed_feedback:
            if choice not in YES | NO:
                return self._menu(lang)
            turn.feedback = "yes" if choice in YES else "no"
            s.awaiting_feedback = False
            return Reply(kind="thanks", lang=lang, text=self._t(lang, "thanks"))

        s.awaiting_feedback = False
        if event.type == "location":
            return await self._location(event, s, turn, lang)
        if event.type == "voice":
            return await self._voice(event, s, turn, lang)
        if event.type == "text":
            text = (event.text or "").strip()
            turn.transcript = for_storage(text)
            return await self._text(text, s, turn, lang) if text else self._menu(lang)
        return self._menu(lang)

    # ---------------------------------------------------------------- input paths

    async def _location(self, event: Event, s: Session, turn: _Turn, lang: Lang) -> Reply:
        if event.lat is None or event.lng is None:
            return self._error(lang, "location_denied")
        start = time.perf_counter()
        try:
            # Coordinates go to this one call and nowhere else (not the session, not the log).
            result = await self.postcode.reverse(event.lat, event.lng)
        except PostcodeError as exc:
            return self._postcode_error(lang, exc, turn)
        finally:
            turn.latency.api = _ms(start)

        turn.postcode_found = result.found
        turn.api_status = "found" if result.found else "not_found"
        if not result.found or result.postcode is None:
            return Reply(kind="postcode", lang=lang, text=self._t(lang, "postcode_not_found"))

        segs = self._segments(lang, result.postcode)
        lines = [self._t(lang, "postcode_result", display=display(result.postcode)), *_seg_lines(segs)]
        confidence = result.confidence if result.confidence in ("high", "medium", "low") else None
        if confidence != "high" and result.distance_m is not None:
            lines.append(self._t(lang, "confidence_low", distance=round(result.distance_m)))
        s.awaiting_feedback = True
        return Reply(
            kind="postcode",
            lang=lang,
            text=self._with_feedback(lang, lines),
            postcode=result.postcode,
            segments=segs,
            confidence=confidence,  # type: ignore[arg-type]
        )

    async def _voice(self, event: Event, s: Session, turn: _Turn, lang: Lang) -> Reply:
        start = time.perf_counter()
        try:
            transcript = (await self.asr.transcribe(event.audio or b"", lang, event.audio_mime)).strip()
        except AsrError as exc:
            log_event("asr_error", kind=exc.kind, lang=lang)
            turn.api_status = f"asr_{exc.kind}"
            return self._error(lang, ASR_ERROR_TEMPLATES[exc.kind])
        except Exception as exc:
            log_event("asr_error", kind="unexpected", error=type(exc).__name__, lang=lang)
            turn.api_status = "asr_unavailable"
            return self._error(lang, "error_generic")
        finally:
            turn.latency.asr = _ms(start)

        if not transcript:
            return self._error(lang, "not_heard")
        turn.transcript = for_storage(transcript)
        reply = await self._text(transcript, s, turn, lang)
        heard = self._t(lang, "we_heard", transcript=transcript)
        extra = [self._t(lang, "igbo_beta")] if lang == "ig" else []
        reply.text = "\n".join([heard, reply.text, *extra])
        reply.transcript = transcript
        return reply

    async def _text(self, text: str, s: Session, turn: _Turn, lang: Lang) -> Reply:
        code = find_postcode(text)
        if code:  # a code in the text is checked directly; the LLM is not needed
            turn.intent = "validate_postcode"
            return await self._validate(code, s, turn, lang)

        start = time.perf_counter()
        try:
            intent: Intent = (await self.intent.classify(text, lang)).intent
            turn.llm_status = "ok"
        except Exception as exc:  # LLM down or cold: fall back to keywords, never fail the turn
            turn.llm_status = _llm_status(exc)
            log_event("llm_error", stage="intent", status=turn.llm_status, error=type(exc).__name__)
            intent = "other"
        finally:
            turn.latency.llm = _ms(start)
        if intent == "other":
            intent = safety_net(text)
        # The log keeps what the LLM said; on LLM failure that is "other" (llm_status says why).
        turn.intent = "other" if turn.llm_status != "ok" else intent

        if intent == "get_my_postcode":
            return Reply(kind="ask_location", lang=lang, text=self._t(lang, "ask_location"))
        if intent == "validate_postcode":  # no code was found in the text
            return Reply(kind="ask_code", lang=lang, text=self._t(lang, "ask_code"))
        if intent == "explain_postcode":
            return await self._explain(text, s, turn, lang)
        return self._menu(lang)

    async def _validate(self, code: str, s: Session, turn: _Turn, lang: Lang) -> Reply:
        start = time.perf_counter()
        try:
            result = await self.postcode.lookup(code)
        except PostcodeError as exc:
            return self._postcode_error(lang, exc, turn)
        finally:
            turn.latency.api = _ms(start)

        turn.api_status = result.status
        turn.postcode_found = result.valid
        if result.status == "bad_format":
            return Reply(kind="validation", lang=lang, text=self._t(lang, "validation_bad_format"))
        s.awaiting_feedback = True
        if not result.valid:
            text = self._t(lang, "validation_not_found", display=display(result.postcode))
            return Reply(kind="validation", lang=lang, text=self._with_feedback(lang, [text]))
        segs = self._segments(lang, result.postcode)
        lines = [self._t(lang, "validation_valid", display=display(result.postcode)), *_seg_lines(segs)]
        return Reply(
            kind="validation",
            lang=lang,
            text=self._with_feedback(lang, lines),
            postcode=result.postcode,
            segments=segs,
        )

    async def _explain(self, question: str, s: Session, turn: _Turn, lang: Lang) -> Reply:
        start = time.perf_counter()
        try:
            answer = await self.reply.explain(question, lang)
        except Exception as exc:
            turn.llm_status = _llm_status(exc)
            log_event("llm_error", stage="explain", status=turn.llm_status, error=type(exc).__name__)
            answer = None
        finally:
            turn.latency.llm = (turn.latency.llm or 0) + _ms(start)

        if not _safe_answer(answer):
            turn.reply_kind = "template_fallback"
            answer = self._t(lang, "explain_fallback")
        s.awaiting_feedback = True
        return Reply(kind="answer", lang=lang, text=self._with_feedback(lang, [answer or ""]))

    # ---------------------------------------------------------------- replies

    def _t(self, lang: Lang, key: str, **values: Any) -> str:
        text = self.templates[lang].get(key) or self.templates["en"][key]
        return text.format(**values) if values else text

    def _welcome(self, lang: Lang) -> Reply:
        text = f"{self._t(lang, 'welcome')}\n\n{self._t(lang, 'attribution')}"
        return Reply(kind="welcome", lang=lang, text=text)

    def _language_menu(self, lang: Lang) -> Reply:
        """Each language named in itself, then the attribution. No other text on this screen."""
        options = [f"{i} {self._t(code, 'language_name')}" for i, code in enumerate(MENU_ORDER, 1)]
        text = "\n".join(options) + f"\n\n{self._t('en', 'attribution')}"
        return Reply(kind="language_menu", lang=lang, text=text)

    def _menu(self, lang: Lang) -> Reply:
        return Reply(kind="menu", lang=lang, text=self._t(lang, "menu"))

    def _error(self, lang: Lang, key: str) -> Reply:
        return Reply(kind="error", lang=lang, text=self._t(lang, key))

    def _postcode_error(self, lang: Lang, exc: PostcodeError, turn: _Turn) -> Reply:
        turn.api_status = exc.kind
        if exc.kind in ALERT_KINDS:
            log_event("alert", source="postcode_api", kind=exc.kind)
        return self._error(lang, POSTCODE_ERROR_TEMPLATES.get(exc.kind, "error_generic"))

    def _with_feedback(self, lang: Lang, lines: list[str]) -> str:
        return "\n".join([*lines, self._t(lang, "feedback_question")])

    def _segments(self, lang: Lang, code: str) -> list[tuple[str, str]]:
        """[("LA", "Lagos"), ("11", "your Local Government Area"), ...]. Unknown states are never guessed."""
        (state, state_name), *rest = segments(code, self.states)
        labels = [self._t(lang, key) for key in SEGMENT_KEYS]
        state_label = state_name or self._t(lang, "seg_state_code")
        return [(state, state_label)] + [(part, label) for (part, _), label in zip(rest, labels, strict=True)]

    # ---------------------------------------------------------------- logging

    async def _count_decline(self) -> None:
        try:
            await self.declines.increment()
        except Exception as exc:
            log_event("decline_count_error", error=type(exc).__name__)

    async def _write_log(self, event: Event, s: Session, turn: _Turn, reply: Reply) -> None:
        try:
            await self.log.append(
                LogRow(
                    user_hash=event.user_hash,
                    channel=event.channel,
                    lang=s.lang,
                    input=turn.input,
                    transcript=turn.transcript,
                    intent=turn.intent,
                    llm_status=turn.llm_status,
                    postcode_found=turn.postcode_found,
                    api_status=turn.api_status,
                    latency_ms=turn.latency,
                    reply_kind=turn.reply_kind or reply.kind,
                    feedback=turn.feedback,
                    knew_postcode_before=turn.knew_postcode_before,
                )
            )
        except Exception as exc:  # a lost log row must never cost the user their answer
            log_event("log_error", error=type(exc).__name__)


def _input_kind(event: Event) -> InputKind:
    if event.type in ("voice", "text", "location"):
        return event.type
    return "choice"


def _llm_status(exc: Exception) -> LlmStatus:
    if isinstance(exc, LlmError):
        return exc.kind
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "error"


def _seg_lines(segs: list[tuple[str, str]]) -> list[str]:
    return [f"{code} = {label}" for code, label in segs]


def _safe_answer(answer: str | None) -> bool:
    """Second guard on LLM text (llm.py has the first): no URLs, no postcode except the documented example."""
    if not answer or not answer.strip():
        return False
    if _URL_RE.search(answer):
        return False
    codes = {normalise(m.group(0)) for m in POSTCODE_RE.finditer(answer)}
    return codes <= {EXAMPLE_POSTCODE}
