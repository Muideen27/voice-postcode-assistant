# CLAUDE.md: Voice Postcode Assistant (NAIC 2026)

Read this first every session. It is the source of truth for architecture, commands and conventions.
If code and this file disagree, ask before changing either, then update this file in the same change.

## What we are building

A voice-first service that lets Nigerians get, check and understand their **new national postcode**
(live since 1 Oct 2026) by speaking Yoruba, Hausa, Igbo or Nigerian English.

- Competition: National AI Innovation Challenge (NAIC) 2026, **Innovation & Enterprise track**,
  independent developer, **PS2 Voice-First Access**, use case **civic information**.
- **Deadline: 12 Oct 2026, 17:59 WAT. Target submission: 11 Oct.** No new features after 9 Oct.
- Validation requirement: **50+ documented real user interactions** with non-developer users.

## Stack at a glance (exact versions, contracts and budgets live in SPEC.md)

Modal (Python 3.11 images, L4 GPUs) · vLLM serving `NCAIR1/N-ATLaS` · transformers 5.18.0 + torch 2.14.1
for the four `NCAIR1/*` Whisper ASR models · FastAPI 0.142.4 + httpx 0.28.1 · twilio 9.11.2 · Postcode API
(L1 key) · plain HTML/JS web page (< 50 KB). Read `SPEC.md` before writing or changing any component.

## Hard rules (never break these)

1. **Only N-ATLAS models.** Voice input goes through the official `NCAIR1/*` ASR models; language
   understanding and replies go through `NCAIR1/N-ATLaS`. Never call GPT, Claude, Gemini or any other
   foundation model at runtime. Wrapping another model means disqualification.
2. **Facts come from the Postcode API, never from the LLM.** The model never writes, edits or guesses a
   postcode, LGA, district or place name. Postcodes and segment explanations come from API data plus
   native-checked templates. (Tested: N-ATLaS invents place names like "Apapa" when not grounded.)
3. **The user chooses the language; the model never guesses it.** The language selects the ASR model
   and is stated explicitly in every LLM prompt ("Reply ONLY in Yoruba").
4. **Privacy.** No NIN, names or contact details collected. Coordinates are used for one lookup and
   never stored. User IDs are stored only as salted one-way hashes. Audio is deleted after transcription.
5. **N-ATLaS licence.** Show the attribution "N-ATLaS is an initiative of the Federal Ministry of
   Communications, Innovation and Digital Economy, and powered by Awarri Technologies." in the welcome
   message, web footer and docs. Stay under 1,000 active users per 30 days. No surveillance or profiling.
6. **Secrets never go in the repo.** Use Modal secrets. `*.txt` key files and `.env` are git-ignored.

## Architecture

One core, thin channels. All logic lives in the orchestrator; channels only translate messages.

```
 WhatsApp (Twilio webhook)   Web voice page (/, /api/*)
            \                     /
             v                   v
        Channel adapters -> Event{user_hash, lang, type, text, audio_bytes, lat, lng}
                         |
                  Orchestrator (state machine, Modal CPU)
        /            |              |                \
  ASR service    N-ATLaS LLM    Postcode client     Store
  (Modal GPU,    (vLLM, Modal   (NIPOST gateway,    (Modal Dict:
  4 Whisper      L4, OpenAI-    Lookup L1)          sessions; Volume:
  models)        compatible)                        interaction log)
```

### Conversation flow

1. **New user** -> welcome + consent + language menu (1 Yorùbá, 2 Hausa, 3 Igbo, 4 English).
2. **Location** -> `reverse_geocode` -> template reply (code + each segment explained) -> feedback.
3. **Voice note** -> ASR (chosen language) -> same path as text.
4. **Text** -> LLM intent JSON (+ keyword safety net) ->
   - `get_my_postcode` -> ask for location pin (place names alone cannot give a building code at L1)
   - `validate_postcode` -> regex-extract code -> `lookup(level=1)` -> valid / not found
   - `explain_postcode` -> LLM answers from `data/fact_sheet_<lang>.md` only
   - `greeting` / `other` / low confidence -> show menu again
5. **Feedback** (1 = helpful, 2 = not) -> interaction log.

Voice stays the primary path; "Type instead" is a secondary option (PS2 is for people who do not type).

## Repo layout

Status: (exists) = working file today, (planned) = to be written.

```
app/
  orchestrator.py      (planned) state machine, routing, reply assembly
  events.py            (planned) Event dataclass shared by all channels
  channels/
    twilio_whatsapp.py (planned) POST /twilio, TwiML replies, signature check
    web.py             (planned) serves web/index.html, POST /api/voice|location|text|feedback
  services/
    asr.py             (planned) Modal GPU class, loads 4 ASR models once
    llm.py             (planned) client for the vLLM endpoint (intent + reply)
    postcode.py        (planned) reverse_geocode, lookup, disassemble, state table
  templates/           (planned) reply strings per language: en.json, yo.json, ha.json, ig.json
  store.py             (planned) sessions (Modal Dict), interaction log (Volume, JSONL)
data/
  states.json          (planned) 37 state codes -> names
  fact_sheet_<lang>.md (planned) facts the LLM may use for explain_postcode
web/index.html         (planned) low-bandwidth page, < 50 KB, no frameworks
deploy/
  natlas_serve.py      (exists) vLLM on L4, OpenAI-compatible, API-key protected
  twillo_echo.py       (exists) Twilio echo webhook (prototype; note the spelling)
  whatsapp_echo.py     (exists) Meta Cloud API echo webhook (unused: Meta account locked)
tests/
  test_natlas_asr.py   (exists) ASR access check + transcription
  natlas_final_test.py (exists) intent + grounded-reply evals (laptop or Modal)
  test_postcode.py     (planned) API client tests with recorded responses
  test_orchestrator.py (planned) state machine tests with fake services
scripts/
  export_log.py        (planned) interaction log -> CSV/PDF evidence
docs/                  submission PDFs (integration evidence, validation, technical docs, team)
SPEC.md                (exists) stack, pinned versions, constraints, component contracts
requirements.txt       (exists) pinned app dependencies (vllm pinned separately in deploy/natlas_serve.py)
```

## Commands

```bash
# environment (Ubuntu laptop, Python 3.12 venv; Modal images use 3.11)
source venv/bin/activate
pip install -r requirements.txt

# one-time Modal secrets
modal secret create huggingface HF_TOKEN=hf_xxx
modal secret create natlas-api NATLAS_API_KEY=$(cat natlas_api_key.txt)
modal secret create twilio TWILIO_ACCOUNT_SID=AC... TWILIO_AUTH_TOKEN=... \
  TWILIO_WHATSAPP_FROM="whatsapp:+1..." POSTCODE_API_KEY=nipost_test_...

# LLM server
modal serve deploy/natlas_serve.py 2>&1 | tee serve.log   # debug, Ctrl+C stops billing
modal deploy deploy/natlas_serve.py                        # permanent URL
export NATLAS_URL=https://muideen27--natlas-serve-serve.modal.run
export NATLAS_API_KEY=$(cat natlas_api_key.txt)
curl -L "$NATLAS_URL/v1/models" -H "Authorization: Bearer $NATLAS_API_KEY"   # health

# evals
python tests/natlas_final_test.py intent
python tests/natlas_final_test.py reply
python tests/test_natlas_asr.py check
python tests/test_natlas_asr.py yo sample.wav

# app (once written)
modal serve app/main.py          # dev
modal deploy app/main.py         # prod
pytest -q                        # unit tests (no network)
modal app logs <app-name> | tail -n 20
modal app stop <app-name>        # stop anything stuck retrying

# audio prep for manual ASR tests
ffmpeg -i note.ogg -ar 16000 -ac 1 note.wav
```

## External services: facts and gotchas

**N-ATLaS LLM (vLLM on Modal L4)**
- Served model name `natlas`. Max context 4096 here (model card says ~8K).
- `VLLM_USE_FLASHINFER_SAMPLER=0` is required (FlashInfer needs nvcc, which the image lacks).
  `--enforce-eager` keeps startup reliable.
- Cold start takes minutes; warm calls take 2-7 s. Keep `min_containers=1` only during user sessions.
- vLLM uses `repetition_penalty`; llama.cpp (laptop) uses `repeat_penalty`.

**ASR**: `NCAIR1/Yoruba-ASR`, `NCAIR1/Hausa-ASR`, `NCAIR1/Igbo-ASR`, `NCAIR1/NigerianAccentedEnglish`.
Whisper-small fine-tunes (~967 MB each), gated (accept terms on HF). Input 16 kHz mono.
Quality: Yoruba and Hausa good, Igbo weaker (label it beta). Place names come out spelled by sound.

**Postcode API** (`https://api.postcode.gov.ng`, header `X-API-Key`)
- Docs are partly out of date: **every endpoint needs a key**, and the docs' test postcodes return
  `not_found`. Known-valid code for tests: `LA-11-A12-GN-01` (from reverse geocode of 6.6018, 3.3515).
- Our key is **Lookup level 1 only** (validity). Names and addresses need L2 (requested, pending);
  handle `level_not_granted` gracefully.
- `/v1/search/reverse?lat&lng&max_distance_m` returns codes only, no names, plus `confidence`.
- Rate limit 600/window; respect `429`.

**Twilio WhatsApp sandbox**
- Reply **inline with TwiML** from the webhook. The trial blocks free-text outbound API messages
  (`ContentSid Required`). Webhooks must answer within ~15 s.
- Limited trial: 5 testers, ~98 messages, and voice/location were not forwarded. Upgrade before the pilot.
- Users must send the join code once; sandbox sessions lapse after ~3 days without messages.

**Meta WhatsApp Cloud API**: business account locked (error 131031). Do not create new accounts.

## Coding conventions

- Python 3.11 in Modal images. Type hints everywhere; `dataclasses` or Pydantic for payloads.
- FastAPI for HTTP; `httpx.AsyncClient` with explicit timeouts for every outbound call.
- Services sit behind small interfaces so tests use fakes (no network in `pytest`).
- Ruff for lint and format: `ruff check . && ruff format .`.
- Log with `print`/`logging` as one JSON line per event; never log raw phone numbers, coordinates or audio.
- User-facing strings live only in `app/templates/<lang>.json`, never inline in code.
- Language codes everywhere: `en`, `yo`, `ha`, `ig`.
- Every external failure maps to a friendly, localised message plus a next step.

## LLM prompt conventions

- `temperature: 0` for intent; `0.1` max for replies. `max_tokens` 80 (intent) / 200 (reply).
- Intent: system prompt + few-shot examples in **all four languages** (include a noisy ASR transcript),
  plus `response_format` JSON schema with `intent` enum and `places_mentioned`. Then apply the keyword
  safety net (`postcode|pósíkòdì|koodu|lamba|...`) before trusting `other`.
- Replies: state the language twice (system + end of user message); put facts in the **user** turn under
  `FACTS (use only these)`; cap at ~80 words; never ask the model for a postcode or place name.
- Prompt text lives in `app/services/prompts.py`. Change it only together with `tests/natlas_final_test.py`
  and record the new scores in `docs/evals.md`.

## Interaction log schema (validation evidence)

One JSONL row per user turn:
`ts, user_hash, channel(whatsapp|web), lang, input(voice|text|location), transcript, intent,
postcode_found(bool|null), api_status, latency_ms{asr,llm,api,total}, reply_kind, feedback(yes|no|null),
knew_postcode_before(bool|null)`. No coordinates, phone numbers or audio.

## Definition of done for any change

- `pytest -q` passes, and `ruff check .` is clean.
- Templates exist for all four languages (mark untranslated strings `TODO_REVIEW`).
- No new runtime dependency on a non-N-ATLAS model or an unapproved external service.
- This file is updated if commands, layout or rules changed; SPEC.md if versions, contracts or budgets changed.
