"""
N-ATLaS LLM test on Modal.

Step 1 (once, runs on cheap CPU - downloads ~16 GB into a Modal volume):
    modal run natlas_llm_test.py --step download

Step 2 (runs on an L4 GPU - loads the cached model and runs the tests):
    modal run natlas_llm_test.py

Requires:  modal secret create huggingface HF_TOKEN=hf_xxx
"""
import modal

MODEL = "NCAIR1/N-ATLaS"

app = modal.App("natlas-llm-test")
cache = modal.Volume.from_name("hf-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch", "transformers", "accelerate", "huggingface_hub")
    .env({"HF_HOME": "/cache"})  # model files live in the persistent volume
)

SYSTEM = (
    "You are a helpful WhatsApp assistant for Nigeria's new postcode system. "
    "The user's message is a speech-to-text transcript and may contain spelling errors. "
    "Reply briefly and simply, in the same language the user spoke."
)

TESTS = [
    # 1. Real Yoruba ASR transcript (postcode request)
    ("Yoruba postcode request", [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi, mo ń gbé ní ibìẹ̀jùlẹ́kí etí ọ̀sà lagos ni gra ni adojúkọ̀ lawi òtẹ̀"},
    ]),
    # 2. Real Hausa ASR transcript (greeting)
    ("Hausa greeting", [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "ina kona an ta shi lafiya ya gajiya muka masu an ta shi lafiya ya iyali, kowa da kowa, ya kauye, ya baba ya baba."},
    ]),
    # 3. Real Igbo ASR transcript (greeting)
    ("Igbo greeting", [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "ọtụtụ ọma, ndị ewu onu, kedu ka imere ademma?"},
    ]),
    # 4. Explaining a real postcode API result in Yoruba
    ("Yoruba explain lookup result", [
        {"role": "system", "content": SYSTEM + (
            "\n\nPostcode lookup result for the user's shared location: "
            "postcode LA-11-A12-GN-01, valid, high confidence. "
            "Segments: state LA = Lagos, LGA 11, district A12, area GN, building unit 01. "
            "Tell the user their postcode and explain what each part means.")},
        {"role": "user", "content": "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi"},
    ]),
    # 5. Structured extraction - needed to route requests in the app
    ("JSON intent extraction", [
        {"role": "system", "content": (
            "Read the speech transcript and output ONLY a JSON object, no other text, with keys: "
            '"language" (yoruba|hausa|igbo|english), '
            '"intent" (get_my_postcode|validate_postcode|explain_postcode|greeting|other), '
            '"places_mentioned" (list of place names, corrected spelling).')},
        {"role": "user", "content": "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi, mo ń gbé ní ibìẹ̀jùlẹ́kí etí ọ̀sà lagos ni gra ni adojúkọ̀ lawi òtẹ̀"},
    ]),
]


@app.function(image=image, volumes={"/cache": cache}, secrets=[hf_secret], timeout=1800)
def download():
    from huggingface_hub import snapshot_download
    path = snapshot_download(MODEL)
    cache.commit()
    print("Downloaded to", path)


@app.function(image=image, gpu="L4", volumes={"/cache": cache}, secrets=[hf_secret], timeout=900)
def run_tests():
    import time
    from datetime import datetime

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="cuda")
    print(f"Model loaded in {time.time() - t0:.1f}s\n")

    for name, messages in TESTS:
        prompt = tok.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False,
            date_string=datetime.now().strftime("%d %b %Y"),
        )
        inputs = tok(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")

        t = time.time()
        out = model.generate(**inputs, max_new_tokens=250, do_sample=False, repetition_penalty=1.12)
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        reply = tok.decode(new_tokens, skip_special_tokens=True).strip()
        secs = time.time() - t

        print("=" * 70)
        print(f"TEST: {name}   ({len(new_tokens)} tokens in {secs:.1f}s)")
        print("-" * 70)
        print(reply, "\n")


@app.local_entrypoint()
def main(step: str = "test"):
    if step == "download":
        download.remote()
    else:
        run_tests.remote()
