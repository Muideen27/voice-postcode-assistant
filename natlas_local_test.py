"""
Run the 5 N-ATLaS tests against a local llama.cpp server (no extra packages needed).

1. Start the server in another terminal:
   ./llama.cpp/build/bin/llama-server -m models/N-ATLaS-GGUF-Q4_K_M.gguf -c 2048 -t 4 --port 8080
2. Run:  python natlas_local_test.py          (all tests)
         python natlas_local_test.py 1        (just test 1)
"""
import json
import sys
import time
import urllib.request

URL = "http://localhost:8080/v1/chat/completions"

SYSTEM = (
    "You are a helpful WhatsApp assistant for Nigeria's new postcode system. "
    "The user's message is a speech-to-text transcript and may contain spelling errors. "
    "Reply briefly and simply, in the same language the user spoke."
)

TESTS = [
    ("Yoruba postcode request", [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi, mo ń gbé ní ibìẹ̀jùlẹ́kí etí ọ̀sà lagos ni gra ni adojúkọ̀ lawi òtẹ̀"},
    ]),
    ("Hausa greeting", [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "ina kona an ta shi lafiya ya gajiya muka masu an ta shi lafiya ya iyali, kowa da kowa, ya kauye, ya baba ya baba."},
    ]),
    ("Igbo greeting", [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "ọtụtụ ọma, ndị ewu onu, kedu ka imere ademma?"},
    ]),
    ("Yoruba explain lookup result", [
        {"role": "system", "content": SYSTEM + (
            "\n\nPostcode lookup result for the user's shared location: "
            "postcode LA-11-A12-GN-01, valid, high confidence. "
            "Segments: state LA = Lagos, LGA 11, district A12, area GN, building unit 01. "
            "Tell the user their postcode and explain what each part means.")},
        {"role": "user", "content": "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi"},
    ]),
    ("JSON intent extraction", [
        {"role": "system", "content": (
            "Read the speech transcript and output ONLY a JSON object, no other text, with keys: "
            '"language" (yoruba|hausa|igbo|english), '
            '"intent" (get_my_postcode|validate_postcode|explain_postcode|greeting|other), '
            '"places_mentioned" (list of place names, corrected spelling).')},
        {"role": "user", "content": "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi, mo ń gbé ní ibìẹ̀jùlẹ́kí etí ọ̀sà lagos ni gra ni adojúkọ̀ lawi òtẹ̀"},
    ]),
]


def ask(messages):
    body = json.dumps({
        "messages": messages,
        "max_tokens": 200,
        "temperature": 0.1,
        "repeat_penalty": 1.12,
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"].strip(), data.get("usage", {})


if __name__ == "__main__":
    picked = [int(a) for a in sys.argv[1:]] or range(1, len(TESTS) + 1)
    for i in picked:
        name, messages = TESTS[i - 1]
        t = time.time()
        reply, usage = ask(messages)
        print("=" * 70)
        print(f"TEST {i}: {name}   ({usage.get('completion_tokens', '?')} tokens in {time.time() - t:.1f}s)")
        print("-" * 70)
        print(reply, "\n")