"""N-ATLaS client (vLLM, OpenAI-compatible): IntentService and ReplyService. Contract: SPEC.md §3.4-3.5.

One call per request, no retry inside a user turn. Failures raise LlmError(kind), which the orchestrator
logs as llm_status and turns into the keyword safety net (intent) or the template answer (explain).
"""

import json
import os
import re
import unicodedata
from typing import Any

import httpx

from app.events import Lang
from app.services import prompts
from app.services.interfaces import IntentResult, LlmError
from app.services.postcode import POSTCODE_RE, normalise

# Web budget: a cold turn must answer within 180 s (SPEC §2). The first call of a turn absorbs the cold
# start; any second call in the same turn is warm.
TIMEOUT = httpx.Timeout(150.0, connect=10.0)
GUARD_MAX_WORDS = 120

_URL_RE = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|ng|org|net|gov)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+")
_WORD_RE = re.compile(r"[^\W\d_]+")
# Places the model might invent (tested: it adds "Apapa" when ungrounded). Matched on folded text.
PLACE_NAMES = (
    "abia adamawa akwa ibom anambra bauchi bayelsa benue borno cross river delta ebonyi edo ekiti enugu "
    "gombe imo jigawa kaduna kano katsina kebbi kogi kwara lagos legas nasarawa niger ogun ondo osun oyo "
    "plateau rivers sokoto taraba yobe zamfara abuja fct federal capital territory "
    "ikeja lekki ibeju apapa surulere yaba victoria island ikorodu epe badagry ajah ojota oshodi "
    "ibadan port harcourt onitsha aba benin jos ilorin abeokuta owerri calabar uyo warri maiduguri zaria "
    "akure osogbo ado umuahia awka yola makurdi lokoja lafia minna gusau dutse jalingo damaturu birnin kebbi"
).split()
_PLACE_RE = re.compile(
    r"\b(?:" + "|".join(sorted({re.escape(p) for p in PLACE_NAMES}, key=len, reverse=True)) + r")\b"
)
_ENGLISH_WORDS = set(
    "the is and your you of to a in it for are this that we can with on be by or has have what how "
    "postcodes not from where".split()
)


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def guard(answer: str, facts: str, lang: Lang) -> str | None:
    """Reason the answer must not be shown, or None if it passes. Facts come only from FACTS."""
    if _URL_RE.search(answer):
        return "url"
    allowed_codes = {normalise(m.group(0)) for m in POSTCODE_RE.finditer(facts)}
    if any(normalise(m.group(0)) not in allowed_codes for m in POSTCODE_RE.finditer(answer)):
        return "postcode_not_in_facts"
    words = answer.split()
    if len(words) > GUARD_MAX_WORDS:
        return "too_long"
    if set(_NUMBER_RE.findall(answer)) - set(_NUMBER_RE.findall(facts)):
        return "number_not_in_facts"
    if set(_PLACE_RE.findall(fold(answer))) - set(_PLACE_RE.findall(fold(facts))):
        return "place_not_in_facts"
    if lang != "en":
        tokens = [w for w in _WORD_RE.findall(answer.lower()) if len(w) > 1]
        if tokens and sum(w in _ENGLISH_WORDS for w in tokens) / len(tokens) > 0.3:
            return "wrong_language"
    return None


class NatlasClient:
    """POST /v1/chat/completions with the API key. Returns the message content or raises LlmError."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: httpx.Timeout = TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,  # Modal web endpoints may redirect while a container starts
        )

    @classmethod
    def from_env(cls) -> "NatlasClient":
        return cls(os.environ["NATLAS_URL"], os.environ["NATLAS_API_KEY"])

    async def aclose(self) -> None:
        await self._http.aclose()

    async def chat(self, payload: dict[str, Any]) -> str:
        try:
            response = await self._http.post("/v1/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LlmError("timeout", type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise LlmError("error", type(exc).__name__) from exc
        if response.status_code >= 400:
            raise LlmError("error", f"HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmError("error", "unexpected response shape") from exc
        if not isinstance(content, str):
            raise LlmError("error", "no content")
        return content.strip()


class NatlasIntent:
    """IntentService: few-shot + JSON schema classification."""

    def __init__(self, client: NatlasClient) -> None:
        self._client = client

    async def classify(self, text: str, lang: Lang) -> IntentResult:
        content = await self._client.chat(prompts.intent_payload(text, lang))
        try:
            data = json.loads(content)
            intent = data["intent"]
            confidence = float(data.get("confidence", 1.0))
            places = data.get("places_mentioned") or []
        except (ValueError, KeyError, TypeError) as exc:
            raise LlmError("bad_json", content[:80]) from exc
        if intent not in prompts.INTENTS or not isinstance(places, list):
            raise LlmError("bad_json", content[:80])
        return IntentResult(
            intent=intent,
            confidence=min(max(confidence, 0.0), 1.0),
            places_mentioned=tuple(str(p) for p in places),
        )


class NatlasExplain:
    """ReplyService: answers from the fact sheet only; None when the guard rejects the answer."""

    def __init__(self, client: NatlasClient, facts: dict[Lang, str] | None = None) -> None:
        self._client = client
        self._facts = facts or {lang: prompts.load_fact_sheet(lang) for lang in prompts.LANG_NAMES}
        self.last_guard_reason: str | None = None  # for evals and logging

    async def explain(self, question: str, lang: Lang) -> str | None:
        facts = self._facts[lang]
        answer = await self._client.chat(prompts.explain_payload(question, lang, facts))
        self.last_guard_reason = guard(answer, facts, lang)
        if self.last_guard_reason:
            print(json.dumps({"event": "llm_guard_reject", "reason": self.last_guard_reason, "lang": lang}))
            return None
        return answer
