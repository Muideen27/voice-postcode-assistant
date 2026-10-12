---
title: "N-ATLaS integration — Voice Postcode Assistant"
---

# N-ATLaS integration

**Voice Postcode Assistant** · Team VoxPost NG · NAIC 2026 · Innovation & Enterprise track · PS2 Voice-First Access ·
Live: <https://muideen27--voice-postcode-web.modal.run> · Code: <https://github.com/Muideen27/voice-postcode-assistant>

N-ATLaS is an initiative of the Federal Ministry of Communications, Innovation and Digital Economy, and
powered by Awarri Technologies.

## 1. What the models do

The service helps Nigerians get, check and understand their new national postcode by **speaking Yorùbá,
Hausa, Igbo or Nigerian English**. Every AI step uses an official N-ATLaS model; no other AI model is
called at runtime.

| Step | Model (Hugging Face) | Pinned revision | Where it runs |
|---|---|---|---|
| Speech to text, Yorùbá | `NCAIR1/Yoruba-ASR` | `d1ae7b8b79c2` | Modal, NVIDIA L4 |
| Speech to text, Hausa | `NCAIR1/Hausa-ASR` | `e635b9eda290` | Modal, NVIDIA L4 |
| Speech to text, Igbo (beta) | `NCAIR1/Igbo-ASR` | `180732299d5c` | Modal, NVIDIA L4 |
| Speech to text, Nigerian English | `NCAIR1/NigerianAccentedEnglish` | `3c52c6e6c9ec` | Modal, NVIDIA L4 |
| Understanding the request (intent + FAQ topic) | `NCAIR1/N-ATLaS` (Llama-3 8B fine-tune, BF16) | `main` (vLLM) | Modal, NVIDIA L4, vLLM 0.30.0 |

Facts never come from a model. Postcodes and their validity come from the official **Nigeria Postcode
API** (NIPOST gateway, Lookup level 1); explanations come from reviewed templates. This rule exists
because, in our own tests, N-ATLaS invented place names (for example "Apapa", "Ikoyi-Obalende") when it
was not grounded.

## 2. How a voice note flows through the models

1. The user **chooses** the language on the first screen. The model never guesses it.
2. The phone records up to 20 s (`MediaRecorder`). The server decodes it with ffmpeg through pipes to
   16 kHz mono PCM; audio is never written to disk and is discarded after transcription.
3. The ASR model **for the chosen language** transcribes it on the GPU (all four are loaded once per
   container at the pinned revisions).
4. If the transcript contains a postcode (for example "LA 11 A12 GN 01"), it is checked directly with the
   Postcode API. **The language model is not called** for a code check or for a location.
5. Otherwise **N-ATLaS** classifies the request into strict JSON (section 3). A keyword safety net in all
   four languages covers low-confidence or failed calls.
6. The reply is a **reviewed template** in the user's language, filled with API data only.

## 3. N-ATLaS as a classifier: the intent JSON schema

N-ATLaS is served with vLLM (OpenAI-compatible API, model name `natlas`, `--max-model-len 4096`,
`--enforce-eager`, API key required). Each request uses `temperature: 0`, `max_tokens: 80`,
`repetition_penalty: 1.12` and a JSON schema, so the output is always machine-readable:

```json
{
  "type": "object",
  "properties": {
    "intent": {"type": "string", "enum": ["get_my_postcode", "validate_postcode", "explain_postcode", "greeting", "other"]},
    "faq_id": {"type": "string", "enum": ["what_is", "parts", "since_when", "get_mine", "check_one",
                                           "place_name_no", "privacy", "who_built", "none"]},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "places_mentioned": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["intent", "faq_id", "confidence", "places_mentioned"],
  "additionalProperties": false
}
```

The system prompt names the user's language ("The user chose Yoruba…") and is followed by **20 few-shot
pairs**, at least two per language, each language with one noisy speech transcript, and every `faq_id`
covered. All prompt text lives in one file, `app/services/prompts.py`; the evals import it, so what is
tested is exactly what runs.

Routing after the model (one pure function, `resolve_route`, shared by the app and the evals):

- postcode found in the text → Postcode API lookup, no LLM;
- confidence below 0.5, timeout (20 s), or invalid JSON → treated as `other`;
- `other` → keyword safety net (e.g. `pósíkòdì`, `koodu`, `lamba`, `ziri ezi`, `daidai`), accents ignored;
- `get_my_postcode` that names a street, road or "name" → the `place_name_no` answer (we cannot find a
  building code from a name; the user is offered the location button).

## 4. FAQ routing, and why free-text generation is off

Explanations are answered by **FAQ routing**: N-ATLaS picks the topic (`faq_id`), and the reply is the
reviewed template for that topic (eight topics, each at most 60 words, facts only from a fixed fact sheet).
Free-text generation is kept in the code (`EXPLAIN_MODE=generate`) for evaluation, but **it is off in
production** because our evals showed (section 6):

- one answer in twelve invented places ("Legas … Gundumar Ikoyi-Obalende") as the meaning of a postcode;
- one answer promised something we cannot do ("give me your exact address" → we find your postcode);
- generated answers took 6.7 s (p50) and 11.1 s (p95), against ~2.7 s for one classification call.

For generate mode a **guard** rejects any answer with a URL or domain, a postcode not in the facts, more
than 120 words, a number not in the facts, a Nigerian place name not in the facts, a capitalised word not
in the facts, the question or a small allowlist, or (Yorùbá/Hausa/Igbo) more than 30% English words. The
orchestrator checks URLs and postcodes a second time.

## 5. Real requests and responses (captured 11 Oct 2026, deployed service)

No secrets are shown: the browser's random session ID is replaced by `<session uuid>`, and API keys are
never part of a request body.

**(a) A raw N-ATLaS classification call** (`docs/submission/examples/natlas_intent.json`). Request
(few-shot pairs omitted for space), then the model's JSON:

```json
{"model": "natlas", "temperature": 0, "max_tokens": 80, "repetition_penalty": 1.12,
 "response_format": {"type": "json_schema", "json_schema": {"name": "intent", "schema": "…as above…"}},
 "messages": [
   {"role": "system", "content": "You classify messages sent to a Nigerian postcode assistant. The user chose Yoruba; …"},
   "… 20 few-shot pairs …",
   {"role": "user", "content": "ki ni itumo posikodi tuntun yi"}]}
```

```json
{"intent": "explain_postcode", "faq_id": "none", "confidence": 0.9, "places_mentioned": []}
```

Annotation: a noisy, accent-less Yorùbá question ("what does this new postcode mean") is recognised as a
request for an explanation; with `faq_id` `none` the app answers with the general explanation template
plus the menu. Time: 3.0 s (warm).

**(b) A Yorùbá voice note through the deployed page** (`web_session.json`, step 4):

```json
{"request": {"method": "POST", "path": "/api/voice",
             "body": {"session": "<session uuid>", "audio": "<yo_test-02.wav, 595070 bytes, audio/wav>"}},
 "response": {"kind": "ask_location", "lang": "yo",
   "transcript": "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi, mo ń gbé ní ibìẹ̀jùlẹ́kí etí ọ̀sà lagos ni gra ni adojúkọ̀ lawi òtẹ̀",
   "text": "Ohun tí a gbọ́: \"ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi, …\"\nLáti rí pósíkòdì yín, ẹ dúró sí ilé yín kí ẹ tẹ \"Gba pósíkòdì mi\" …"}}
```

Annotation: `NCAIR1/Yoruba-ASR` produced the transcript with tone marks; N-ATLaS classified it as
`get_my_postcode`; the reply asks for the location, because a place name alone cannot give a building
postcode. Total 13.8 s for an 18.6 s recording (ASR and LLM warm).

**(c) A code check never calls the language model** (`code_check_unconfirmed.json`, captured after the
canary-aware reply was deployed):

```json
{"request": {"method": "POST", "path": "/api/text", "body": {"session": "<session uuid>", "text": "Is LA-11-A12-GN-01 correct?"}},
 "response": {"kind": "validation", "lang": "en", "postcode": null,
   "text": "LA 11 A12 GN 01 has the right format, but the official postcode database can't confirm it today. Here is what each part means:\nLA = Lagos\n11 = your Local Government Area\nA12 = your district\nGN = your area\n01 = your building\nDid this help?",
   "segments": [["LA", "Lagos"], ["11", "your Local Government Area"], ["A12", "your district"], ["GN", "your area"], ["01", "your building"]]}}
```

Annotation: the postcode is found by the pattern match and checked with the Postcode API (2.1 s, no LLM).
The API answered `not_found`, but the service's data check (every 30 minutes) shows the official database is not
answering for known codes today (validation report, limitations), so the reply does not call the code
wrong: it says the format is right, that the database can't confirm it today, and explains each part from
the state table and reviewed labels. `postcode` stays empty because nothing confirmed it. When the
database is healthy, a missing code is reported as not found.

All eight captured steps (language, consent, the "did you know" question, voice, location, typed
question, code check, feedback) returned HTTP 200 in 1.4–13.8 s.

## 6. Evaluation results (from `evals/results.md`)

Held-out cases (never used as few-shot examples; a unit test enforces this). Live endpoint, NVIDIA L4.

| Run (UTC) | Code | What was measured | Result |
|---|---|---|---|
| 2026-10-08 20:16 | `7f1a489` | Intent, 40 cases (10 per language, noisy transcripts) | 92.5% (en 10/10, yo 10/10, ha 9/10, ig 8/10); 100% valid JSON |
| 2026-10-08 20:16 | `7f1a489` | Generated explanations, 12 cases | guard passed 10/12; 1 invented place (blocked); 1 false promise (not blocked) → generation turned off |
| 2026-10-08 20:50 | `06ac9be` | Intent, 40 cases, with FAQ few-shot | **97.5%** (en 10/10, yo 10/10, ha 9/10, ig 10/10); 100% valid JSON |
| 2026-10-08 20:50 | `06ac9be` | FAQ routing, 20 cases (5 per language) | 16/20; all 4 misses were street-name questions |
| 2026-10-09 08:23 | `97c4cd5` | Street / place-name subset, 12 cases | **12/12** — all through the rule: N-ATLaS classifies these as `get_my_postcode`, and `resolve_route` sends them to `place_name_no` |

Latency (warm): intent p50 2.6 s, p95 3.2 s. GPU cold start: LLM 101–349 s (measured on different days),
ASR 19–76 s. The page wakes both GPUs when it opens and, while a model is cold, shows "Waking up the
language model, about 2 minutes, the first time only" instead of failing.

Speech recognition was checked offline on recorded clips (Yorùbá, Hausa, Igbo, English); word accuracy is
**not** measured live in the pilot. Igbo is labelled beta in the app.

## 7. Licence and responsible use

- Attribution shown on the first screen, the welcome message, every footer and these documents.
- Fewer than 1,000 active users per 30 days; no profiling or surveillance.
- No names, phone numbers or NIN are asked for. Coordinates are used for one lookup and never stored.
  Users are stored only as salted one-way hashes. Stored text is scrubbed of numbers, phones and emails
  and capped at 300 characters.
