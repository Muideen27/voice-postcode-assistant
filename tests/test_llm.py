"""N-ATLaS client tests through httpx.MockTransport. No network."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.events import LANGS
from app.services import prompts
from app.services.interfaces import LlmError
from app.services.llm import NatlasClient, NatlasExplain, NatlasIntent, fold, guard

FACTS = {lang: prompts.load_fact_sheet(lang) for lang in LANGS}


def chat_response(content: Any) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def client(handler: Callable[[httpx.Request], httpx.Response]) -> NatlasClient:
    return NatlasClient("https://natlas.example", "secret", transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def capture(content: Any, seen: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {"url": str(request.url), "auth": request.headers["Authorization"], **json.loads(request.content)}
        )
        return chat_response(content)

    return handler


# ---------------------------------------------------------------- prompts


def test_few_shot_covers_every_language_with_at_least_two_examples() -> None:
    # 3 per language, in order en, yo, ha, ig (see prompts.py); each answer is schema-shaped JSON.
    assert len(prompts.INTENT_FEW_SHOT) >= 8
    for _, answer in prompts.INTENT_FEW_SHOT:
        data = json.loads(answer)
        assert data["intent"] in prompts.INTENTS and 0 <= data["confidence"] <= 1


def test_fact_sheets_hold_only_allowed_codes_and_numbers() -> None:
    for lang, facts in FACTS.items():
        assert "review:" not in facts, lang  # front matter stripped
        assert "LA-11-A12-GN-01" in facts and "AA-99-H77-BB-55" in facts, lang
        # A sheet checked against itself passes every rule except length (sheets are ~130 words).
        assert guard(facts, facts, lang) in (None, "too_long"), lang


# ---------------------------------------------------------------- intent


def test_intent_request_follows_conventions() -> None:
    seen: list[dict[str, Any]] = []
    content = json.dumps({"intent": "get_my_postcode", "confidence": 0.92, "places_mentioned": ["Ojota"]})
    result = run(NatlasIntent(client(capture(content, seen))).classify("mo fe mo posikodi mi", "yo"))

    assert (result.intent, result.confidence, result.places_mentioned) == (
        "get_my_postcode",
        0.92,
        ("Ojota",),
    )
    assert result.faq_id is None
    req = seen[0]
    assert req["url"] == "https://natlas.example/v1/chat/completions"
    assert req["auth"] == "Bearer secret"
    assert (req["model"], req["temperature"], req["max_tokens"]) == ("natlas", 0, 80)
    schema = req["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["intent"]["enum"] == list(prompts.INTENTS)
    assert set(schema["required"]) == {"intent", "faq_id", "confidence", "places_mentioned"}
    assert schema["properties"]["faq_id"]["enum"] == [*prompts.FAQ_IDS, "none"]
    assert "Yoruba" in req["messages"][0]["content"]
    assert req["messages"][-1] == {"role": "user", "content": "mo fe mo posikodi mi"}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"intent": "buy_bread", "confidence": 0.9, "places_mentioned": []}',
        '{"confidence": 0.9}',
        '{"intent": "greeting", "confidence": "high", "places_mentioned": []}',
        '{"intent": "greeting", "confidence": 0.9, "places_mentioned": "Lagos"}',
        '{"intent": "explain_postcode", "faq_id": "history", "confidence": 0.9, "places_mentioned": []}',
    ],
)
def test_intent_bad_json(content: str) -> None:
    with pytest.raises(LlmError) as err:
        run(NatlasIntent(client(lambda r: chat_response(content))).classify("hi", "en"))
    assert err.value.kind == "bad_json"


def test_intent_confidence_is_clamped() -> None:
    content = '{"intent": "greeting", "confidence": 3, "places_mentioned": []}'
    assert run(NatlasIntent(client(lambda r: chat_response(content))).classify("hi", "en")).confidence == 1.0


@pytest.mark.parametrize(
    ("handler", "kind"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), "timeout"),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)), "error"),
        (lambda r: httpx.Response(500, text="boom"), "error"),
        (lambda r: httpx.Response(401, json={"error": "bad key"}), "error"),
        (lambda r: httpx.Response(200, text="<html>"), "error"),
        (lambda r: httpx.Response(200, json={"choices": []}), "error"),
    ],
)
def test_transport_failures_map_to_llm_status(handler: Any, kind: str) -> None:
    with pytest.raises(LlmError) as err:
        run(NatlasIntent(client(handler)).classify("hi", "en"))
    assert err.value.kind == kind


def test_no_retry_inside_a_turn() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(LlmError):
        run(NatlasIntent(client(handler)).classify("hi", "en"))
    assert calls == 1


# ---------------------------------------------------------------- explain


def test_explain_request_follows_conventions() -> None:
    seen: list[dict[str, Any]] = []
    answer = "Pósíkòdì ní apá márùn-ún."
    explain = NatlasExplain(client(capture(answer, seen)), FACTS)
    assert run(explain.explain("kí ni GN túmọ̀ sí?", "yo")) == answer

    req = seen[0]
    assert (req["temperature"], req["max_tokens"]) == (0.1, 200)
    system, user = req["messages"][0]["content"], req["messages"][1]["content"]
    assert "ONLY in Yoruba" in system
    assert user.startswith("kí ni GN túmọ̀ sí?")
    assert "FACTS (use only these):\n" + FACTS["yo"] in user
    assert user.endswith("Answer in Yoruba only, in at most 80 words.")
    assert "response_format" not in req


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ("Visit https://postcode.gov.ng to learn more.", "url"),
        ("Check nipost.gov.ng for details.", "url"),
        ("Your postcode is LA-11-B07-KD-03.", "postcode_not_in_facts"),
        ("word " * 121, "too_long"),
        ("A postcode has 5 parts.", "number_not_in_facts"),
        ("Postcodes in Apapa start with LA.", "place_not_in_facts"),
        ("Postcodes started in Lagos.", "place_not_in_facts"),
    ],
)
def test_guard_rejects_english(answer: str, reason: str) -> None:
    explain = NatlasExplain(client(lambda r: chat_response(answer)), FACTS)
    assert run(explain.explain("what is a postcode", "en")) is None
    assert explain.last_guard_reason == reason


def test_guard_rejects_english_reply_to_a_hausa_user() -> None:
    answer = "The postcode has five parts and it is written like AA-99-H77-BB-55."
    assert guard(answer, FACTS["ha"], "ha") == "wrong_language"


@pytest.mark.parametrize(
    ("answer", "lang"),
    [
        ("A postcode has five parts, like AA-99-H77-BB-55. In LA-11-A12-GN-01, LA is the state.", "en"),
        ("They have been live since 1 October 2026.", "en"),
        ("Postcode tana da sassa biyar. A cikin LA-11-A12-GN-01, LA ita ce jiha.", "ha"),
        ("Postcode nwere akụkụ ise. LA bụ steeti, 11 bụ ọchịchị ime obodo (LGA).", "ig"),
    ],
)
def test_guard_accepts_grounded_answers(answer: str, lang: str) -> None:
    assert guard(answer, FACTS[lang], lang) is None  # type: ignore[arg-type]


def test_explain_errors_propagate_for_llm_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LlmError) as err:
        run(NatlasExplain(client(handler), FACTS).explain("what is a postcode", "en"))
    assert err.value.kind == "timeout"


def test_eval_cases_are_held_out_from_few_shot() -> None:
    from evals.cases import EXPLAIN_CASES, FAQ_CASES, INTENT_CASES

    shots = {fold(text) for text, _ in prompts.INTENT_FEW_SHOT}
    cases = [text for rows in INTENT_CASES.values() for text, _ in rows]
    faq = [text for rows in FAQ_CASES.values() for text, _ in rows]
    assert len(faq) == 20 and all(len(rows) == 5 for rows in FAQ_CASES.values())
    assert {fid for rows in FAQ_CASES.values() for _, fid in rows} <= set(prompts.FAQ_IDS)
    assert not shots & {fold(text) for text in faq}
    assert len(cases) == 40 and all(len(rows) == 10 for rows in INTENT_CASES.values())
    assert all(len(qs) == 3 for qs in EXPLAIN_CASES.values())
    assert not shots & {fold(text) for text in cases}


# ---------------------------------------------------------------- FAQ routing, warm-up, timeout


@pytest.mark.parametrize(
    ("intent", "faq_id", "expected"),
    [
        ("explain_postcode", "place_name_no", "place_name_no"),
        ("explain_postcode", "none", None),
        ("greeting", "parts", None),  # faq_id only counts for explain_postcode
    ],
)
def test_intent_returns_faq_id(intent: str, faq_id: str, expected: str | None) -> None:
    content = json.dumps({"intent": intent, "faq_id": faq_id, "confidence": 0.9, "places_mentioned": []})
    result = run(NatlasIntent(client(lambda r: chat_response(content))).classify("q", "en"))
    assert result.faq_id == expected


def test_few_shot_covers_every_faq_id() -> None:
    ids = {json.loads(answer)["faq_id"] for _, answer in prompts.INTENT_FEW_SHOT}
    assert ids == {*prompts.FAQ_IDS, "none"}


def test_turn_timeout_is_20_seconds() -> None:
    from app.services.llm import TIMEOUT

    assert TIMEOUT.read == 20.0


def test_warm_sends_a_one_token_request_and_swallows_errors() -> None:
    seen: list[dict[str, Any]] = []
    run(client(capture("x", seen)).warm())
    assert seen[0]["max_tokens"] == 1

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    run(client(down).warm())  # no exception


@pytest.mark.parametrize(
    ("answer", "question", "reason"),
    [
        ("In LA-11-A12-GN-01, the district is in Ikoyi.", "", "unknown_capitalised_word"),
        ("The area code GN stands for Obalende here.", "", "unknown_capitalised_word"),
        ("Your area in Gbagada has its own code.", "I live in Gbagada", None),  # from the question
        ("Each part has a meaning. The state comes first.", "", None),  # sentence-initial capitals
        ("Postcode tana da sassa biyar a Najeriya.", "", None),  # allowlisted country name
    ],
)
def test_guard_capitalised_words(answer: str, question: str, reason: str | None) -> None:
    assert guard(answer, FACTS["en"], "en", question) == reason
