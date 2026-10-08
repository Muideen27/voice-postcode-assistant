"""
N-ATLaS text-input postcode tests (clean text, no ASR errors).

Needs the llama.cpp server running:
   ./llama.cpp/build/bin/llama-server -m models/N-ATLaS-GGUF-Q4_K_M.gguf -c 2048 -t 4 --port 8080

Usage:
   python natlas_text_test.py grounded      # most important - answer using real API data
   python natlas_text_test.py json          # intent extraction
   python natlas_text_test.py plain         # model answers alone, no data
   python natlas_text_test.py all           # all 9 tests (slow on CPU: ~10-15 min)
"""
import json
import sys
import time
import urllib.request

URL = "http://localhost:8080/v1/chat/completions"

QUESTIONS = {
    "yoruba": "Jọ̀wọ́, kí ni kóòdù ìfìwéránṣẹ́ (postcode) fún ibi tí mo ń gbé? Mo ń gbé ní Ibeju Lekki, Ìpínlẹ̀ Èkó, Nàìjíríà.",
    "hausa": "Don Allah, menene lambar gidan waya (postcode) ta wurin da nake zaune? Ina zaune a Ibeju Lekki, Jihar Legas, Najeriya.",
    "igbo": "Biko, kedu koodu ozi (postcode) maka ebe m bi? Ana m ebi na Ibeju Lekki, na Steeti Lagos, Naịjirịa.",
}

# Sample result from our real reverse-geocode test (used here only to test how the model uses data)
LOOKUP = (
    "[Postcode lookup result from the Nigeria Postcode API for the user's shared location]\n"
    "Postcode: LA-11-A12-GN-01 (valid, high confidence)\n"
    "LA = state (Lagos), 11 = Local Government Area, A12 = district, GN = area, 01 = building unit.\n"
    "Using ONLY this result, tell the user their postcode and briefly explain each part."
)

SYSTEM_CHAT = (
    "You are a helpful WhatsApp assistant for Nigeria's new postcode system. "
    "Reply briefly and simply, in the same language the user wrote in. "
    "Never invent postcodes, websites or facts."
)

SYSTEM_JSON = (
    "Read the user's message and output ONLY a JSON object, no other text, with keys: "
    '"language" (yoruba|hausa|igbo|english), '
    '"intent" (get_my_postcode|validate_postcode|explain_postcode|greeting|other), '
    '"places_mentioned" (list of place names, corrected spelling).'
)


def build(mode, question):
    if mode == "plain":
        return [{"role": "system", "content": SYSTEM_CHAT},
                {"role": "user", "content": question}]
    if mode == "json":
        return [{"role": "system", "content": SYSTEM_JSON},
                {"role": "user", "content": question}]
    # grounded: real data placed in the USER turn, after the question
    return [{"role": "system", "content": SYSTEM_CHAT},
            {"role": "user", "content": question + "\n\n" + LOOKUP}]


def ask(messages):
    body = json.dumps({"messages": messages, "max_tokens": 200,
                       "temperature": 0.1, "repeat_penalty": 1.12}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"].strip(), data.get("usage", {})


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "grounded"
    modes = ["grounded", "json", "plain"] if arg == "all" else [arg]
    for mode in modes:
        for lang, question in QUESTIONS.items():
            t = time.time()
            reply, usage = ask(build(mode, question))
            print("=" * 70)
            print(f"[{mode.upper()}] {lang}   ({usage.get('completion_tokens', '?')} tokens in {time.time() - t:.1f}s)")
            print("-" * 70)
            print(reply, "\n")
