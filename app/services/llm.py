"""N-ATLaS client (vLLM, OpenAI-compatible): IntentService and ReplyService. Contract: SPEC.md §3.4-3.5.

One call per request, no retry inside a user turn. Failures raise LlmError(kind), which the orchestrator
logs as llm_status and turns into the keyword safety net (intent) or the template answer (explain).

Production uses FAQ routing (EXPLAIN_MODE=faq): the intent call returns a faq_id and the answer is a
reviewed template. NatlasExplain (free-text generation + guard) is kept for EXPLAIN_MODE=generate only.
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

# Per-turn budget (SPEC §2): 20 s. A cold GPU takes ~2 min, so a cold turn times out and the orchestrator
# answers with the keyword safety net or the warming_up template; /api/warm starts the GPU on page load.
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
WARM_TIMEOUT = httpx.Timeout(600.0, connect=10.0)  # warm() waits out a full cold start in the background
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
_TOKEN_RE = re.compile(r"[^\W\d_][\w'’-]*")
_SENTENCE_START = set(".!?:#-•*(\n")
# Capitalised words always allowed in an answer: language and country names, abbreviations, months.
CAPITALISED_ALLOWLIST = set(
    "i english yoruba yorùbá hausa igbo nigeria nigerian nigeria's naijiria najeriya nàìjíríà naịjirịa "
    "lga nin ok api n-atlas october oktoba ọktoba".split()
)


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _unknown_capitalised(answer: str, allowed_text: str) -> str | None:
    """First capitalised word that is not at a sentence start and not in FACTS, the question or the allowlist."""
    vocabulary = {fold(t) for t in _TOKEN_RE.findall(allowed_text)} | {fold(w) for w in CAPITALISED_ALLOWLIST}
    for match in _TOKEN_RE.finditer(answer):
        token = match.group(0)
        if not token[0].isupper() or fold(token) in vocabulary:
            continue
        before = answer[: match.start()].rstrip(" \t\"“'‘")
        if not before or before[-1] in _SENTENCE_START:
            continue  # sentence-initial capital
        return token
    return None


def guard(answer: str, facts: str, lang: Lang, question: str = "") -> str | None:
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
    if _unknown_capitalised(answer, f"{facts}\n{question}"):
        return "unknown_capitalised_word"
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

    async def warm(self) -> None:
        """Wake the GPU: one 1-token request with a long timeout. Run it as a background task (/api/warm);
        never inside a user turn. Errors are swallowed: warming is best effort."""
        payload = {"model": "natlas", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
        try:
            await self._http.post("/v1/chat/completions", json=payload, timeout=WARM_TIMEOUT)
        except httpx.HTTPError as exc:
            print(json.dumps({"event": "llm_warm_error", "error": type(exc).__name__}))

    async def ready(self, timeout_s: float = 2.5) -> bool:
        """True if the LLM answers /v1/models within timeout_s (warm); False while it is cold or starting."""
        try:
            response = await self._http.get("/v1/models", timeout=timeout_s)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

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
            faq_id = data.get("faq_id", "none")
            confidence = float(data.get("confidence", 1.0))
            places = data.get("places_mentioned") or []
        except (ValueError, KeyError, TypeError) as exc:
            raise LlmError("bad_json", content[:80]) from exc
        valid_faq = faq_id in prompts.FAQ_IDS or faq_id == "none"
        if intent not in prompts.INTENTS or not valid_faq or not isinstance(places, list):
            raise LlmError("bad_json", content[:80])
        return IntentResult(
            intent=intent,
            confidence=min(max(confidence, 0.0), 1.0),
            faq_id=faq_id if intent == "explain_postcode" and faq_id != "none" else None,
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
        self.last_guard_reason = guard(answer, facts, lang, question)
        if self.last_guard_reason:
            print(json.dumps({"event": "llm_guard_reject", "reason": self.last_guard_reason, "lang": lang}))
            return None
        return answer
