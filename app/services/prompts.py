"""All N-ATLaS prompt text and request settings. Contract: CLAUDE.md "LLM prompt conventions", SPEC.md §3.4-3.5.

Change this file only together with evals/natlas_final_test.py, and record new scores in evals/results.md.
Eval inputs (evals/cases.py) must never repeat a few-shot example below.
"""

import json
from pathlib import Path
from typing import Any

from app.events import Lang

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LANG_NAMES: dict[Lang, str] = {"en": "English", "yo": "Yoruba", "ha": "Hausa", "ig": "Igbo"}
INTENTS = ("get_my_postcode", "validate_postcode", "explain_postcode", "greeting", "other")
LOW_CONFIDENCE = 0.5  # below this the orchestrator treats the intent as "other"

# ---------------------------------------------------------------- intent

INTENT_PARAMS: dict[str, Any] = {"temperature": 0, "max_tokens": 80, "repetition_penalty": 1.12}

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "places_mentioned": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "confidence", "places_mentioned"],
    "additionalProperties": False,
}

INTENT_SYSTEM = (
    "You classify messages sent to a Nigerian postcode assistant. The user chose {language}; the message "
    "is in {language} or mixed with English, and it may be a speech transcript with spelling mistakes and "
    "missing accents. Polite words like 'please' do NOT make a message a greeting.\n"
    "Intents:\n"
    "- get_my_postcode: asks for their own postcode or the postcode of where they live\n"
    "- validate_postcode: asks if a postcode is real, valid or correct\n"
    "- explain_postcode: asks what a postcode is, what its parts mean, or how it works\n"
    "- greeting: only greets or thanks, with no request\n"
    "- other: anything else\n"
    "Reply with JSON only: intent, confidence (0 to 1) and places_mentioned (place names in the message, "
    "copied as written; empty list if none)."
)


def _shot(intent: str, confidence: float, places: list[str] | None = None) -> str:
    return json.dumps({"intent": intent, "confidence": confidence, "places_mentioned": places or []})


# Two or more per language, one noisy ASR-style transcript each. Never reuse these as eval cases.
INTENT_FEW_SHOT: list[tuple[str, str]] = [
    # English
    (
        "Please, what is the postcode for my house? I live in Ikeja, Lagos.",
        _shot("get_my_postcode", 0.95, ["Ikeja", "Lagos"]),
    ),
    ("good morning how is your family", _shot("greeting", 0.95)),
    ("what does the GN part of my post code mean", _shot("explain_postcode", 0.9)),
    # Yoruba
    ("Ẹ jọ̀wọ́, ṣé pósíkòdì tí wọ́n fún mi tọ̀nà?", _shot("validate_postcode", 0.9)),
    ("e kaaro ma se daadaa ni", _shot("greeting", 0.9)),
    ("mo fe mo posikodi ile mi ni ojota", _shot("get_my_postcode", 0.9, ["ojota"])),
    # Hausa
    ("Don Allah, menene ma'anar sassan postcode?", _shot("explain_postcode", 0.9)),
    ("ina son sanin lamba gidan waya na a kano", _shot("get_my_postcode", 0.9, ["kano"])),
    ("sannu da aiki", _shot("greeting", 0.95)),
    # Igbo
    ("Biko, kedu postcode ụlọ m? Ana m ebi n'Enugu.", _shot("get_my_postcode", 0.95, ["Enugu"])),
    ("biko postcode a o ziri ezi", _shot("validate_postcode", 0.85)),
    ("kedu ka i mere", _shot("greeting", 0.9)),
]


def intent_messages(text: str, lang: Lang) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": INTENT_SYSTEM.format(language=LANG_NAMES[lang])}]
    for example, answer in INTENT_FEW_SHOT:
        messages.append({"role": "user", "content": example})
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": text})
    return messages


def intent_payload(text: str, lang: Lang) -> dict[str, Any]:
    return {
        "model": "natlas",
        "messages": intent_messages(text, lang),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "intent", "schema": INTENT_SCHEMA},
        },
        **INTENT_PARAMS,
    }


# ---------------------------------------------------------------- explain

EXPLAIN_PARAMS: dict[str, Any] = {"temperature": 0.1, "max_tokens": 200, "repetition_penalty": 1.12}
EXPLAIN_MAX_WORDS = 80

EXPLAIN_SYSTEM = (
    "You are a helpful assistant that explains Nigeria's new postcodes. "
    "You MUST reply ONLY in {language}. "
    "Use only the FACTS given in the user's message. Do not add any other information, websites, "
    "postcodes, place names or numbers. If the FACTS do not answer the question, say so briefly and "
    "suggest sharing a location or saying the postcode. Keep the reply under {words} words."
)


def load_fact_sheet(lang: Lang, data_dir: Path = DATA_DIR) -> str:
    """Fact sheet body without its front matter (the `review:` marker)."""
    text = (data_dir / f"fact_sheet_{lang}.md").read_text(encoding="utf-8")
    if text.startswith("---\n"):
        text = text.split("\n---\n", 1)[1]
    return text.strip()


def explain_messages(question: str, lang: Lang, facts: str) -> list[dict[str, str]]:
    language = LANG_NAMES[lang]
    system = EXPLAIN_SYSTEM.format(language=language, words=EXPLAIN_MAX_WORDS)
    user = (
        f"{question}\n\n"
        f"FACTS (use only these):\n{facts}\n\n"
        f"Answer in {language} only, in at most {EXPLAIN_MAX_WORDS} words."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def explain_payload(question: str, lang: Lang, facts: str) -> dict[str, Any]:
    return {"model": "natlas", "messages": explain_messages(question, lang, facts), **EXPLAIN_PARAMS}
