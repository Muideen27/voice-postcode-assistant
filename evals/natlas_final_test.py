"""
Final N-ATLaS test - the two jobs the LLM keeps in the new design.

Works against either backend:
   Laptop (llama.cpp):  default, no env vars needed
   Modal (vLLM):        export NATLAS_URL=https://<your-modal-url>   NATLAS_API_KEY=<your key>

Usage:
   python evals/natlas_final_test.py reply     # A: grounded replies with the language stated explicitly (3 tests)
   python evals/natlas_final_test.py intent    # B: few-shot + JSON-schema intent detection (5 tests)
   python evals/natlas_final_test.py all
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("NATLAS_URL", "http://localhost:8080").rstrip("/")
URL = BASE + "/v1/chat/completions"
API_KEY = os.environ.get("NATLAS_API_KEY", "")
IS_VLLM = "localhost" not in BASE

QUESTIONS = {
    "Yoruba": "Jọ̀wọ́, kí ni kóòdù ìfìwéránṣẹ́ (postcode) fún ibi tí mo ń gbé? Mo ń gbé ní Ibeju Lekki, Ìpínlẹ̀ Èkó, Nàìjíríà.",
    "Hausa": "Don Allah, menene lambar gidan waya (postcode) ta wurin da nake zaune? Ina zaune a Ibeju Lekki, Jihar Legas, Najeriya.",
    "Igbo": "Biko, kedu koodu ozi (postcode) maka ebe m bi? Ana m ebi na Ibeju Lekki, na Steeti Lagos, Naịjirịa.",
}

# ---------------------------------------------------------------- A: replies
FACTS = (
    "FACTS (use only these):\n"
    "- The user's postcode is LA-11-A12-GN-01.\n"
    "- LA = Lagos State. 11 = Local Government Area number. A12 = district code. "
    "GN = area code. 01 = building number.\n"
    "- The letters and numbers are codes, not words in any language."
)


def reply_messages(lang, question):
    system = (
        f"You are a helpful WhatsApp postcode assistant. "
        f"You MUST reply ONLY in {lang}. Never reply in English. "
        f"Use only the FACTS given. Do not add websites or any other information. "
        f"Keep the reply under 80 words."
    )
    user = f"{question}\n\n{FACTS}\n\nAnswer in {lang} only."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------------------------------------------------------- B: intent
INTENTS = ["get_my_postcode", "validate_postcode", "explain_postcode", "greeting", "other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "places_mentioned": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "places_mentioned"],
}

INTENT_SYSTEM = (
    "Classify the user's message. The message may be in Yoruba, Hausa, Igbo or English, "
    "and may be a speech transcript with spelling errors. Polite words like 'please' do NOT make it a greeting. "
    "Output JSON with 'intent' and 'places_mentioned'.\n"
    "Intents: get_my_postcode (asks for their own postcode), validate_postcode (asks if a code is real/correct), "
    "explain_postcode (asks what a postcode or its parts mean), greeting (only greets, no request), other."
)

# English few-shot examples, so the test inputs below are never shown to the model
FEW_SHOT = [
    ("Please, what is the postcode for my house? I live in Ikeja, Lagos.",
     {"intent": "get_my_postcode", "places_mentioned": ["Ikeja", "Lagos"]}),
    ("Good morning, how are you and your family?",
     {"intent": "greeting", "places_mentioned": []}),
    ("Is KN-31-F82-WJ-80 a correct postcode?",
     {"intent": "validate_postcode", "places_mentioned": []}),
    ("What does the LA part of my postcode mean?",
     {"intent": "explain_postcode", "places_mentioned": []}),
]

INTENT_TESTS = [
    ("Yoruba clean question", QUESTIONS["Yoruba"], "get_my_postcode"),
    ("Hausa clean question", QUESTIONS["Hausa"], "get_my_postcode"),
    ("Igbo clean question", QUESTIONS["Igbo"], "get_my_postcode"),
    ("Yoruba ASR transcript",
     "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi, mo ń gbé ní ibìẹ̀jùlẹ́kí etí ọ̀sà lagos ni gra ni adojúkọ̀ lawi òtẹ̀",
     "get_my_postcode"),
    ("Hausa ASR greeting",
     "ina kona an ta shi lafiya ya gajiya muka masu an ta shi lafiya ya iyali, kowa da kowa, ya kauye, ya baba ya baba.",
     "greeting"),
]


def intent_messages(text):
    msgs = [{"role": "system", "content": INTENT_SYSTEM}]
    for example, answer in FEW_SHOT:
        msgs.append({"role": "user", "content": example})
        msgs.append({"role": "assistant", "content": json.dumps(answer)})
    msgs.append({"role": "user", "content": text})
    return msgs


# ---------------------------------------------------------------- shared
def ask(messages, max_tokens, schema=None):
    payload = {"model": "natlas", "messages": messages, "max_tokens": max_tokens, "temperature": 0.1}
    # same setting, different name on each server
    payload["repetition_penalty" if IS_VLLM else "repeat_penalty"] = 1.12
    if schema:
        # llama.cpp grammar-constrains the output so it can only match this schema
        payload["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "intent", "schema": schema}}
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=900) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"].strip(), data.get("usage", {})


def run_reply():
    for lang, q in QUESTIONS.items():
        t = time.time()
        out, usage = ask(reply_messages(lang, q), max_tokens=200)
        print("=" * 70)
        print(f"[REPLY] {lang}   ({usage.get('completion_tokens', '?')} tokens in {time.time() - t:.1f}s)")
        print("-" * 70)
        print(out, "\n")


def run_intent():
    score = 0
    for name, text, expected in INTENT_TESTS:
        t = time.time()
        out, _ = ask(intent_messages(text), max_tokens=80, schema=SCHEMA)
        try:
            got = json.loads(out).get("intent")
        except json.JSONDecodeError:
            got = "INVALID JSON"
        ok = got == expected
        score += ok
        print("=" * 70)
        print(f"[INTENT] {name}   ({time.time() - t:.1f}s)   {'PASS' if ok else 'FAIL'} "
              f"(expected {expected}, got {got})")
        print("-" * 70)
        print(out, "\n")
    print(f"INTENT SCORE: {score}/{len(INTENT_TESTS)}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("reply", "all"):
        run_reply()
    if mode in ("intent", "all"):
        run_intent()
