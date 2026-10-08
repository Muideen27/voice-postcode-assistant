"""Orchestrator tests with fake services. No network, no Modal, no models."""

import asyncio
import json
from typing import Any

import pytest

from app.events import Event, Lang
from app.orchestrator import Orchestrator, load_templates, safety_net
from app.services.interfaces import AsrError, IntentResult, LlmError
from app.services.postcode import LookupResult, PostcodeError, ReverseResult, load_states
from app.store import MemoryDeclineCounter, MemoryLog, MemorySessionStore, Session, hash_user

USER = hash_user("salt", "web", "session-1")
VALID = "LA-11-A12-GN-01"
INVALID = "LA-11-W06-TC-10"
T = load_templates()
FOUND = ReverseResult(
    found=True, postcode=VALID, display="LA 11 A12 GN 01", confidence="high", distance_m=9.2
)


# ---------------------------------------------------------------- fakes


class FakePostcode:
    def __init__(self, reverse: ReverseResult | Exception = FOUND, lookup: Exception | None = None) -> None:
        self._reverse = reverse
        self._lookup = lookup
        self.calls: list[tuple[str, Any]] = []

    async def reverse(self, lat: float, lng: float) -> ReverseResult:
        self.calls.append(("reverse", (lat, lng)))
        if isinstance(self._reverse, Exception):
            raise self._reverse
        return self._reverse

    async def lookup(self, code: str) -> LookupResult:
        self.calls.append(("lookup", code))
        if self._lookup:
            raise self._lookup
        return LookupResult(code, code == VALID, "valid" if code == VALID else "not_found")


class FakeIntent:
    def __init__(self, intent: str | Exception = "other") -> None:
        self._intent = intent
        self.calls: list[tuple[str, str]] = []

    async def classify(self, text: str, lang: Lang) -> IntentResult:
        self.calls.append((text, lang))
        if isinstance(self._intent, Exception):
            raise self._intent
        return IntentResult(self._intent)  # type: ignore[arg-type]


class FakeReply:
    def __init__(self, answer: str | None | Exception = "A postcode has five parts.") -> None:
        self._answer = answer
        self.calls: list[tuple[str, str]] = []

    async def explain(self, question: str, lang: Lang) -> str | None:
        self.calls.append((question, lang))
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


class FakeAsr:
    def __init__(self, transcript: str | Exception = "") -> None:
        self._transcript = transcript
        self.calls: list[tuple[bytes, str, str | None]] = []

    async def transcribe(self, audio: bytes, lang: Lang, mime: str | None = None) -> str:
        self.calls.append((audio, lang, mime))
        if isinstance(self._transcript, Exception):
            raise self._transcript
        return self._transcript


class Harness:
    def __init__(self, **services: Any) -> None:
        self.postcode = services.get("postcode", FakePostcode())
        self.intent = services.get("intent", FakeIntent())
        self.reply = services.get("reply", FakeReply())
        self.asr = services.get("asr", FakeAsr())
        self.sessions = services.get("sessions", MemorySessionStore())
        self.log = services.get("log", MemoryLog())
        self.declines = services.get("declines", MemoryDeclineCounter())
        self.orch = Orchestrator(
            postcode=self.postcode,
            intent=self.intent,
            reply=self.reply,
            asr=self.asr,
            sessions=self.sessions,
            log=self.log,
            declines=self.declines,
            states=load_states(),
            templates=T,
        )

    def send(self, type_: str, text: str | None = None, **kw: Any):
        event = Event(user_hash=USER, channel="web", type=type_, lang=kw.pop("lang", None), text=text, **kw)
        return asyncio.run(self.orch.handle(event))

    def onboard(self, lang: Lang = "en", knew: str = "skip") -> None:
        self.send("text", "hi")
        self.send("choice", lang)
        self.send("choice", "agree")
        self.send("choice", knew)
        self.log.rows.clear()

    @property
    def last_row(self) -> dict[str, Any]:
        return json.loads(self.log.rows[-1].to_json())

    def session(self) -> Session:
        return asyncio.run(self.sessions.get(USER))


def ready(lang: Lang = "en", **services: Any) -> Harness:
    h = Harness(**services)
    h.onboard(lang)
    return h


# ---------------------------------------------------------------- onboarding


def test_first_screen_is_language_menu_with_attribution_only() -> None:
    h = Harness()
    reply = h.send("text", "hello")
    assert reply.kind == "language_menu"
    assert reply.text == f"1 Yorùbá\n2 Hausa\n3 Igbo\n4 English\n\n{T['en']['attribution']}"
    assert h.log.rows == []
    assert USER not in h.sessions.data  # nothing stored until a language is chosen


@pytest.mark.parametrize("lang", ["en", "yo", "ha", "ig"])
def test_onboarding_order_language_consent_knew_before_menu(lang: Lang) -> None:
    h = Harness()
    assert h.send("text", "hello").kind == "language_menu"
    welcome = h.send("choice", lang)
    assert (welcome.kind, welcome.lang) == ("welcome", lang)
    assert welcome.text.startswith(T[lang]["welcome"])
    assert T["en"]["attribution"] in welcome.text
    assert h.log.rows == []  # no consent yet
    ask = h.send("choice", "agree")
    assert (ask.kind, ask.lang, ask.text) == ("ask_knew_before", lang, T[lang]["ask_knew_before"])
    done = h.send("choice", "skip")
    assert (done.kind, done.lang) == ("menu", lang)
    assert h.session().stage == "ready"


def test_language_digit_selects_menu_order() -> None:
    h = Harness()
    h.send("text", "hi")
    assert h.send("choice", "2").lang == "ha"


def test_knew_before_is_asked_before_any_postcode_is_shown() -> None:
    h = Harness()
    h.send("text", "hi")
    h.send("choice", "en")
    h.send("choice", "agree")
    reply = h.send("location", lat=6.6018, lng=3.3515)  # tries to skip the question
    assert reply.kind == "ask_knew_before"
    assert h.postcode.calls == []


@pytest.mark.parametrize(("answer", "expected"), [("yes", True), ("no", False), ("skip", None), ("1", True)])
def test_knew_before_answers_are_logged(answer: str, expected: bool | None) -> None:
    h = Harness()
    h.send("text", "hi")
    h.send("choice", "yo")
    h.send("choice", "agree")
    reply = h.send("choice", answer)
    assert reply.kind == "menu"
    assert h.last_row["knew_postcode_before"] is expected
    assert h.last_row["lang"] == "yo"


def test_knew_before_is_asked_only_once() -> None:
    h = ready("en")
    assert h.send("choice", "yo").kind == "menu"  # language change in ready
    assert h.session().stage == "ready"
    assert h.session().lang == "yo"


def test_invalid_answers_reprompt_each_stage() -> None:
    h = Harness()
    h.send("text", "hi")
    assert h.send("choice", "9").kind == "language_menu"
    h.send("choice", "en")
    assert h.send("choice", "maybe").kind == "welcome"
    h.send("choice", "agree")
    assert h.send("choice", "perhaps").kind == "ask_knew_before"


def test_language_can_be_changed_on_the_consent_screen() -> None:
    h = Harness()
    h.send("text", "hi")
    h.send("choice", "en")
    welcome = h.send("choice", "ig")
    assert (welcome.kind, welcome.lang) == ("welcome", "ig")


@pytest.mark.parametrize("lang", ["en", "ha"])
def test_decline_deletes_session_counts_and_logs_nothing(lang: Lang) -> None:
    h = Harness()
    h.send("text", "hi")
    h.send("choice", lang)
    reply = h.send("choice", "decline")
    assert (reply.kind, reply.lang, reply.text) == ("declined", lang, T[lang]["declined"])
    assert USER not in h.sessions.data
    assert h.log.rows == []
    assert list(h.declines.counts.values()) == [1]


def test_decline_counter_failure_is_harmless() -> None:
    class BrokenCounter(MemoryDeclineCounter):
        async def increment(self) -> None:
            raise ConnectionError("dict down")

    h = Harness(declines=BrokenCounter())
    h.send("text", "hi")
    h.send("choice", "en")
    assert h.send("choice", "decline").kind == "declined"


# ---------------------------------------------------------------- location


@pytest.mark.parametrize("lang", ["en", "yo"])
def test_location_happy_path(lang: Lang) -> None:
    h = ready(lang)
    reply = h.send("location", lat=6.6018, lng=3.3515)

    assert (reply.kind, reply.lang, reply.postcode, reply.confidence) == ("postcode", lang, VALID, "high")
    assert reply.segments == [
        ("LA", "Lagos"),
        ("11", T[lang]["seg_lga"]),
        ("A12", T[lang]["seg_district"]),
        ("GN", T[lang]["seg_area"]),
        ("01", T[lang]["seg_building"]),
    ]
    assert T[lang]["postcode_result"].format(display="LA 11 A12 GN 01") in reply.text
    assert "LA = Lagos" in reply.text
    assert reply.text.endswith(T[lang]["feedback_question"])
    assert h.postcode.calls == [("reverse", (6.6018, 3.3515))]

    row = h.last_row
    assert (row["input"], row["postcode_found"], row["api_status"], row["reply_kind"]) == (
        "location",
        True,
        "found",
        "postcode",
    )
    assert row["latency_ms"]["api"] is not None and row["latency_ms"]["total"] is not None
    assert "6.6018" not in h.log.rows[-1].to_json() and "3.3515" not in h.log.rows[-1].to_json()
    assert "6.6018" not in json.dumps(h.sessions.data)


def test_location_unknown_state_shows_code_only() -> None:
    other = ReverseResult(found=True, postcode="OY-01-B22-KD-07", display="", confidence="high", distance_m=3)
    h = ready("en", postcode=FakePostcode(reverse=other))
    reply = h.send("location", lat=7.4, lng=3.9)
    assert reply.segments[0] == ("OY", T["en"]["seg_state_code"])


def test_location_low_confidence_adds_distance_note() -> None:
    far = ReverseResult(found=True, postcode=VALID, display="", confidence="low", distance_m=181.6)
    h = ready("en", postcode=FakePostcode(reverse=far))
    reply = h.send("location", lat=6.6, lng=3.3)
    assert reply.confidence == "low"
    assert T["en"]["confidence_low"].format(distance=182) in reply.text


def test_location_not_found() -> None:
    h = ready("en", postcode=FakePostcode(reverse=ReverseResult(found=False)))
    reply = h.send("location", lat=9.0, lng=7.0)
    assert reply.text == T["en"]["postcode_not_found"]
    assert (h.last_row["postcode_found"], h.last_row["api_status"]) == (False, "not_found")


def test_location_without_coordinates_skips_api() -> None:
    h = ready("en")
    reply = h.send("location")
    assert (reply.kind, reply.text) == ("error", T["en"]["location_denied"])
    assert h.postcode.calls == []


# ---------------------------------------------------------------- text


@pytest.mark.parametrize(
    ("lang", "text"),
    [("en", "Is LA 11 A12 GN 01 my correct postcode?"), ("yo", "ṣé la-11-a12-gn-01 tọ̀nà?")],
)
def test_postcode_in_text_is_validated_without_llm(lang: Lang, text: str) -> None:
    h = ready(lang)
    reply = h.send("text", text)
    assert (reply.kind, reply.postcode) == ("validation", VALID)
    assert T[lang]["validation_valid"].format(display="LA 11 A12 GN 01") in reply.text
    assert h.intent.calls == []
    assert h.postcode.calls == [("lookup", VALID)]
    row = h.last_row
    assert (row["intent"], row["postcode_found"], row["api_status"], row["transcript"]) == (
        "validate_postcode",
        True,
        "valid",
        text,
    )
    assert row["latency_ms"]["llm"] is None


def test_unknown_code_is_never_valid() -> None:
    h = ready("en")
    reply = h.send("text", f"check {INVALID}")
    assert reply.postcode is None
    assert T["en"]["validation_not_found"].format(display="LA 11 W06 TC 10") in reply.text
    assert "is a valid postcode" not in reply.text
    assert h.last_row["postcode_found"] is False


@pytest.mark.parametrize("lang", ["en", "yo"])
def test_get_my_postcode_asks_for_location(lang: Lang) -> None:
    h = ready(lang, intent=FakeIntent("get_my_postcode"))
    reply = h.send("text", "what is my postcode" if lang == "en" else "kí ni pósíkòdì mi")
    assert (reply.kind, reply.text) == ("ask_location", T[lang]["ask_location"])
    assert h.intent.calls[0][1] == lang
    assert h.last_row["latency_ms"]["llm"] is not None


def test_validate_intent_without_code_asks_for_code() -> None:
    h = ready("en", intent=FakeIntent("validate_postcode"))
    assert h.send("text", "is my code right").kind == "ask_code"


def test_explain_uses_reply_service() -> None:
    h = ready("yo", intent=FakeIntent("explain_postcode"), reply=FakeReply("Pósíkòdì ní apá márùn-ún."))
    reply = h.send("text", "kí ni LA túmọ̀ sí?")
    assert reply.kind == "answer"
    assert reply.text.startswith("Pósíkòdì ní apá márùn-ún.")
    assert h.reply.calls == [("kí ni LA túmọ̀ sí?", "yo")]
    assert h.last_row["reply_kind"] == "answer"


@pytest.mark.parametrize(
    "answer",
    [
        None,
        "",
        RuntimeError("vllm down"),
        "See https://postcode.gov.ng for more.",
        "Your postcode is KN-31-F82-WJ-80.",
        "For example LA-11-A12-GN-01, and yours is OG-02-C33-AB-12.",
    ],
)
def test_explain_falls_back_to_template(answer: Any) -> None:
    h = ready("en", intent=FakeIntent("explain_postcode"), reply=FakeReply(answer))
    reply = h.send("text", "what does each part mean")
    assert reply.text.startswith(T["en"]["explain_fallback"])
    assert h.last_row["reply_kind"] == "template_fallback"


def test_explain_allows_the_documented_example_code() -> None:
    h = ready(
        "en", intent=FakeIntent("explain_postcode"), reply=FakeReply("In LA-11-A12-GN-01, LA is the state.")
    )
    assert h.send("text", "explain please").text.startswith("In LA-11-A12-GN-01")


@pytest.mark.parametrize("intent", ["greeting", "other"])
def test_greeting_and_other_show_menu(intent: str) -> None:
    h = ready("en", intent=FakeIntent(intent))
    assert h.send("text", "good morning").kind == "menu"


# ---------------------------------------------------------------- safety net


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Is my code correct?", "validate_postcode"),
        ("ṣé ó tọ̀nà?", "validate_postcode"),
        ("ina so a duba", "validate_postcode"),
        ("mo fẹ́ mọ pósíkòdì ilé mi", "get_my_postcode"),
        ("mo fe mo posikodi ile mi", "get_my_postcode"),
        ("lambar gidan waya", "get_my_postcode"),
        ("biko koodu ozi", "get_my_postcode"),
        ("good morning", "other"),
    ],
)
def test_safety_net_keywords(text: str, expected: str) -> None:
    assert safety_net(text) == expected


def test_safety_net_turns_other_into_validate() -> None:
    h = ready("en", intent=FakeIntent("other"))
    reply = h.send("text", "is my code correct?")
    assert reply.kind == "ask_code"
    assert h.last_row["intent"] == "validate_postcode"


def test_safety_net_turns_other_into_get_my_postcode() -> None:
    h = ready("yo", intent=FakeIntent("other"))
    assert h.send("text", "pósíkòdì").kind == "ask_location"
    assert h.last_row["intent"] == "get_my_postcode"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (TimeoutError("cold start"), "timeout"),
        (LlmError("timeout"), "timeout"),
        (LlmError("bad_json"), "bad_json"),
        (LlmError("error"), "error"),
        (RuntimeError("boom"), "error"),
    ],
)
def test_llm_failure_falls_back_to_keywords_and_logs_status(error: Exception, status: str) -> None:
    h = ready("ha", intent=FakeIntent(error))
    reply = h.send("text", "menene lambar gidan waya ta?")
    assert (reply.kind, reply.lang) == ("ask_location", "ha")  # routed by the keyword net
    assert (h.last_row["intent"], h.last_row["llm_status"]) == ("other", status)


def test_llm_status_ok_and_absent() -> None:
    h = ready("en", intent=FakeIntent("get_my_postcode"))
    h.send("text", "what is my postcode")
    assert h.last_row["llm_status"] == "ok"
    h.send("text", VALID)  # regex path: LLM not called
    assert h.last_row["llm_status"] is None


def test_explain_failure_sets_llm_status() -> None:
    h = ready("en", intent=FakeIntent("explain_postcode"), reply=FakeReply(LlmError("timeout")))
    h.send("text", "what does GN mean")
    assert (h.last_row["llm_status"], h.last_row["reply_kind"]) == ("timeout", "template_fallback")


# ---------------------------------------------------------------- voice


@pytest.mark.parametrize(
    ("lang", "transcript"),
    [("en", "please what is my postcode"), ("yo", "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi")],
)
def test_voice_happy_path(lang: Lang, transcript: str) -> None:
    h = ready(lang, asr=FakeAsr(transcript), intent=FakeIntent("get_my_postcode"))
    reply = h.send("voice", audio=b"\x1a\x45", audio_mime="audio/webm")

    assert reply.kind == "ask_location"
    assert reply.transcript == transcript
    assert reply.text.startswith(T[lang]["we_heard"].format(transcript=transcript))
    assert T[lang]["ask_location"] in reply.text
    assert h.asr.calls == [(b"\x1a\x45", lang, "audio/webm")]
    assert h.intent.calls == [(transcript, lang)]
    row = h.last_row
    assert (row["input"], row["transcript"], row["intent"]) == ("voice", transcript, "get_my_postcode")
    assert row["latency_ms"]["asr"] is not None and row["latency_ms"]["llm"] is not None


def test_voice_with_postcode_is_validated_without_llm() -> None:
    h = ready("en", asr=FakeAsr("is la 11 a12 gn 01 correct"))
    reply = h.send("voice", audio=b"x")
    assert (reply.kind, reply.postcode) == ("validation", VALID)
    assert h.intent.calls == []


def test_igbo_voice_carries_beta_note() -> None:
    h = ready("ig", asr=FakeAsr("biko kedu koodu ozi m"), intent=FakeIntent("get_my_postcode"))
    assert h.send("voice", audio=b"x").text.endswith(T["ig"]["igbo_beta"])


@pytest.mark.parametrize(
    ("asr", "key"),
    [
        (FakeAsr("   "), "not_heard"),
        (FakeAsr(AsrError("too_long")), "audio_too_long"),
        (FakeAsr(AsrError("bad_audio")), "not_heard"),
        (FakeAsr(AsrError("timeout")), "timeout_retry"),
        (FakeAsr(AsrError("unavailable")), "error_generic"),
        (FakeAsr(RuntimeError("GPU fell over")), "error_generic"),
    ],
)
def test_voice_errors_map_to_templates(asr: FakeAsr, key: str) -> None:
    h = ready("yo", asr=asr)
    reply = h.send("voice", audio=b"x")
    assert (reply.kind, reply.text) == ("error", T["yo"][key])
    assert h.intent.calls == []
    assert len(h.log.rows) == 1


# ---------------------------------------------------------------- postcode API errors


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        ("timeout", "error_slow"),
        ("rate_limited", "error_slow"),
        ("unavailable", "error_unavailable"),
        ("config", "error_generic"),  # includes auth_required
        ("credits", "error_generic"),
        ("level_not_granted", "error_generic"),
    ],
)
@pytest.mark.parametrize("path", ["location", "text"])
def test_postcode_errors_map_to_templates(kind: str, key: str, path: str) -> None:
    error = PostcodeError(kind)  # type: ignore[arg-type]
    h = ready("ha", postcode=FakePostcode(reverse=error, lookup=error))
    reply = h.send("location", lat=6.6, lng=3.3) if path == "location" else h.send("text", VALID)
    assert (reply.kind, reply.lang, reply.text) == ("error", "ha", T["ha"][key])
    assert h.last_row["api_status"] == kind


def test_config_errors_raise_an_alert(capsys: pytest.CaptureFixture[str]) -> None:
    h = ready("en", postcode=FakePostcode(reverse=PostcodeError("config")))
    h.send("location", lat=6.6, lng=3.3)
    alerts = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"alert"' in line]
    assert alerts == [{"event": "alert", "source": "postcode_api", "kind": "config"}]


# ---------------------------------------------------------------- feedback and logging


def test_feedback_after_result() -> None:
    h = ready("en")
    h.send("location", lat=6.6018, lng=3.3515)
    reply = h.send("feedback", "yes")
    assert reply.kind == "thanks"
    assert (h.last_row["feedback"], h.last_row["input"]) == ("yes", "choice")


def test_typed_digit_counts_as_feedback_only_right_after_a_result() -> None:
    h = ready("en", intent=FakeIntent("greeting"))
    h.send("text", VALID)
    assert h.send("text", "2").kind == "thanks"
    assert h.last_row["feedback"] == "no"
    assert h.send("text", "2").kind == "menu"  # no longer awaiting feedback


def test_exactly_one_log_row_per_turn_after_consent() -> None:
    h = Harness(asr=FakeAsr("hello"), intent=FakeIntent("greeting"))
    h.send("text", "hi")  # language menu: not logged
    h.send("choice", "en")  # welcome: not logged (no consent yet)
    h.send("choice", "agree")
    h.send("choice", "no")
    h.send("location", lat=6.6018, lng=3.3515)
    h.send("feedback", "yes")
    h.send("text", VALID)
    h.send("voice", audio=b"x")
    assert len(h.log.rows) == 6
    assert all(row.user_hash == USER for row in h.log.rows)


def test_unexpected_failure_still_returns_a_reply() -> None:
    class BrokenSessions(MemorySessionStore):
        async def get(self, user_hash: str) -> Session:
            raise ConnectionError("modal dict unavailable")

    h = Harness(sessions=BrokenSessions())
    reply = h.send("text", "hi", lang="yo")
    assert (reply.kind, reply.text) == ("error", T["yo"]["error_generic"])


def test_log_failure_does_not_lose_the_reply() -> None:
    class BrokenLog(MemoryLog):
        async def append(self, row: Any) -> None:
            raise OSError("volume full")

    h = Harness(log=BrokenLog())
    h.send("text", "hi")
    h.send("choice", "en")
    h.send("choice", "agree")
    h.send("choice", "skip")
    assert h.send("location", lat=6.6018, lng=3.3515).postcode == VALID


# ---------------------------------------------------------------- privacy


def test_typed_text_is_scrubbed_before_logging_but_used_raw_in_the_turn() -> None:
    h = ready("en")
    text = f"my NIN is 12345678901, phone 0803 123 4567, is {VALID} right?"
    reply = h.send("text", text)
    assert reply.postcode == VALID  # the raw text still found the code
    assert h.last_row["transcript"] == f"my NIN is [NUMBER], phone [PHONE], is {VALID} right?"
    stored = h.log.rows[-1].to_json() + json.dumps(h.sessions.data)
    assert "12345678901" not in stored and "4567" not in stored


def test_voice_transcript_is_scrubbed_and_capped() -> None:
    long = "mo fẹ́ mọ pósíkòdì mi, nọ́mbà mi ni +2348031234567 " + "a" * 400
    h = ready("yo", asr=FakeAsr(long), intent=FakeIntent("get_my_postcode"))
    reply = h.send("voice", audio=b"x")
    assert reply.transcript == long.strip()  # shown back to the user unchanged
    row = h.last_row
    assert "[PHONE]" in row["transcript"] and "2348031234567" not in row["transcript"]
    assert len(row["transcript"]) == 300
