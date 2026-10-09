# CLAUDE.md: Voice Postcode Assistant (NAIC 2026)

Read this first every session. It is the source of truth for architecture, commands and conventions.
If code and this file disagree, ask before changing either, then update this file in the same change.

## What we are building

A voice-first service that lets Nigerians get, check and understand their **new national postcode**
(live since 1 Oct 2026) by speaking Yoruba, Hausa, Igbo or Nigerian English.

- Competition: National AI Innovation Challenge (NAIC) 2026, **Innovation & Enterprise track**,
  independent developer, **PS2 Voice-First Access**, use case **civic information**.
- **PS2 delivery channel: low-bandwidth mobile application** (a mobile web page, < 50 KB, served over
  HTTPS from Modal). Web is the only channel in scope.
- **Deadline: 12 Oct 2026, 17:59 WAT. Target submission: 11 Oct.** No new features after 9 Oct.
- Validation requirement: **50+ documented real user interactions** with non-developer users.

## Stack at a glance (exact versions, contracts and budgets live in SPEC.md)

Modal (Python 3.11 images, L4 GPUs) · vLLM 0.30.0 serving `NCAIR1/N-ATLaS` · transformers 5.18.0 +
torch 2.14.1 for the four `NCAIR1/*` Whisper ASR models · FastAPI 0.142.4 + httpx 0.28.1 · Postcode API
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
   never stored. User IDs are stored only as salted one-way hashes (`HASH_SALT` secret). Audio is deleted
   after transcription.
5. **N-ATLaS licence.** Show the attribution "N-ATLaS is an initiative of the Federal Ministry of
   Communications, Innovation and Digital Economy, and powered by Awarri Technologies." in the welcome
   message, web footer and docs. Stay under 1,000 active users per 30 days. No surveillance or profiling.
6. **Secrets never go in the repo.** Use Modal secrets. `*.txt` key files and `.env` are git-ignored.

## Architecture

One core, thin channel. All logic lives in the orchestrator; the channel only translates requests.

```
             Web voice page (/, /api/*)  -- low-bandwidth mobile application
                         |
                         v
        Web adapter -> Event{user_hash, channel="web", type, lang, text, audio, audio_mime, lat, lng}
                         |
                  Orchestrator (state machine, Modal CPU)
        /            |              |                \
  ASR service    N-ATLaS LLM    Postcode client     Store
  (Modal GPU,    (vLLM, Modal   (NIPOST gateway,    (Modal Dict:
  4 Whisper      L4, OpenAI-    Lookup L1)          sessions; Volume:
  models)        compatible)                        interaction log)
```

### Conversation flow

1. **New user** -> language menu: each language named in itself (1 Yorùbá, 2 Hausa, 3 Igbo,
   4 English) with the N-ATLaS attribution below, nothing else. Nothing is stored until one is chosen.
   -> welcome + consent in the chosen language. Decline -> `declined` template, session deleted, only an
   anonymous daily decline count is kept. Agree -> once per user, **before any postcode is shown**:
   "Did you know your new postcode before today?" (yes / no / skip) -> `knew_postcode_before`
   (skip -> null). Asking after a result would bias the answer. -> menu.
2. **Location** (browser geolocation) -> `reverse` -> template reply (code + each segment explained)
   -> feedback.
3. **Voice note** -> ASR (chosen language) -> same path as text.
4. **Text** -> LLM intent JSON (+ postcode regex and keyword safety net) ->
   - `get_my_postcode` -> ask for location (place names alone cannot give a building code at L1);
     if it names a street, road or "name" -> `faq_place_name_no` instead
   - `validate_postcode` -> regex-extract and normalise code -> `lookup(level=1)` -> valid / not found;
     no code in the text -> `ask_code` (offers both: send the code, or share location)
   - `explain_postcode` -> FAQ routing: the intent call also returns `faq_id`; the reply is the reviewed
     template `faq_<faq_id>` (`none` -> explain fallback + menu). No generated text in production
     (`EXPLAIN_MODE=faq`; `generate` is kept for evals only).
   - LLM timeout (20 s, cold GPU) -> keyword safety net; nothing found -> `warming_up` template
   - `greeting` / `other` / low confidence -> show menu again
5. **Feedback** (1 = helpful, 2 = not) -> interaction log.

Voice stays the primary path; "Type instead" is a secondary option (PS2 is for people who do not type).
If the GPU is cold, the web page shows progress and waits up to 180 s before showing a localised retry
message.

## Repo layout

Status: (exists) = working file today, (planned) = to be written.

```
app/
  main.py              (exists) Modal app `voice-postcode`: web endpoint, wiring, ASR class, session sweep
  orchestrator.py      (exists) state machine, routing, reply assembly, keyword safety net
  events.py            (exists) Event and Reply dataclasses
  channels/
    web.py             (exists) HTTP -> Event; /, /fonts, /api/strings|warm|language|consent|location|voice|text|feedback
  services/
    interfaces.py      (exists) Protocols for intent/reply/ASR/postcode services + IntentResult, AsrError,
                       LlmError
    asr.py             (exists) ffmpeg decode + limits (CPU) and Modal L4 class with the 4 pinned models
    llm.py             (exists) N-ATLaS client: NatlasIntent, NatlasExplain, output guard
    prompts.py         (exists) all LLM prompt text, few-shot, schema, request params
    postcode.py        (exists) reverse, lookup, segments, postcode regex/normalise
  templates/           (exists) reply strings per language: en.json, yo.json, ha.json, ig.json
  store.py             (exists) user hashing, sessions (Modal Dict), interaction log (Volume, JSONL),
                       anonymous daily decline counter (Modal Dict)
  privacy.py           (exists) scrub()/for_storage(): PII removed + 300-char cap before storing text
data/
  states.json          (exists) state codes -> names, documented codes only (11 so far)
  fact_sheet_<lang>.md (exists) source facts for the faq_* templates; sent to the model only in generate mode
web/index.html         (exists) the page (19.6 KB, 6.5 KB gzip), no frameworks; matches web/design/prototype.html
web/design/prototype.html (exists) design source of truth (phone screen of the Prototype tab only)
web/fonts/*.woff2      (exists) self-hosted subset fonts (5 files, 101.3 KiB), built by scripts/build_fonts.py
deploy/
  natlas_serve.py      (exists) vLLM on L4, OpenAI-compatible, API-key protected
tests/                 unit tests only: no network, run by `pytest -q`
  test_postcode.py     (exists) API client tests with recorded responses
  fixtures/postcode/   (exists) API response bodies; see its README for which are live
  test_orchestrator.py (exists) state machine tests with fake services
  test_templates.py    (exists) same keys/placeholders in all languages, attribution verbatim
  test_store.py        (exists) hashing, sessions, log schema and privacy
  test_privacy.py      (exists) NIN, phone, email scrubbing; postcodes survive
  test_review_scripts.py (exists) review sheet round trip
  test_asr.py          (exists) upload checks, ffmpeg decode, silence, timeouts (fake GPU)
  test_web.py          (exists) HTTP -> Event mapping, validation, static files
evals/                 live-model checks (need GPU/network), never collected by pytest
  natlas_final_test.py (exists) live intent + explain evals; imports prompts.py/llm.py (no copies)
  cases.py             (exists) 40 intent + 12 explain held-out cases
  runs/                (exists) one JSON per eval run
  test_natlas_asr.py   (exists) ASR access check + transcription (laptop)
  asr_smoke.py         (exists) live GPU smoke test: `modal run evals/asr_smoke.py --clips yo:yo_test.wav`
  results.md           (exists) eval scores, one entry per prompt change
scripts/
  export_log.py        (planned) interaction log -> CSV/PDF evidence
  record_postcode_fixtures.py (exists) refresh tests/fixtures/postcode from the live API
  review_sheet.py      (exists) templates -> docs/review/<lang>.csv for native-speaker review
  apply_review.py      (exists) filled docs/review/<lang>.csv -> templates, clears _todo_review
  build_fonts.py       (exists) download + subset fonts into web/fonts/ (dev: fonttools, brotli)
  warm.sh              (exists) keep one N-ATLaS GPU warm for a pilot window, then back to 0
  ui_screens.py        (exists) 360 px screenshots, live page vs prototype -> docs/ui-compare/
archive/
  twillo_echo.py       (archived) Twilio WhatsApp echo prototype, see Future work
docs/                  submission PDFs (integration evidence, validation, technical docs, team)
  review/<lang>.csv    (exists) review sheets for yo, ha, ig (all strings except faq_*)
  review/faq_<lang>.csv (exists) short FAQ-answer review sheets
  review/ui_<lang>.csv (exists) page-label review sheets (ui_*, chip, conf_*)
  ui-compare/          (exists) live vs prototype screenshots + README table
SPEC.md                (exists) stack, pinned versions, constraints, component contracts
pyproject.toml         (exists) ruff + pytest config
requirements.txt       (exists) pinned app dependencies (vllm pinned in deploy/natlas_serve.py)
```

## Commands

```bash
# environment (Ubuntu laptop, Python 3.12 venv; Modal images use 3.11)
source venv/bin/activate
pip install -r requirements.txt

# one-time Modal secrets
modal secret create huggingface HF_TOKEN=hf_xxx
modal secret create natlas-api NATLAS_API_KEY=$(cat natlas_api_key.txt)
modal secret create voice-postcode POSTCODE_API_KEY=nipost_test_... HASH_SALT=$(openssl rand -hex 32)

# LLM server
modal serve deploy/natlas_serve.py 2>&1 | tee serve.log   # debug, Ctrl+C stops billing
modal deploy deploy/natlas_serve.py                        # permanent URL
export NATLAS_URL=https://muideen27--natlas-serve-serve.modal.run
export NATLAS_API_KEY=$(cat natlas_api_key.txt)
curl -L "$NATLAS_URL/v1/models" -H "Authorization: Bearer $NATLAS_API_KEY"   # health

# evals (live models; record scores in evals/results.md)
python evals/natlas_final_test.py            # health + intent + explain, writes evals/runs/*.json
python evals/natlas_final_test.py intent
python evals/natlas_final_test.py explain
python evals/test_natlas_asr.py check
python evals/test_natlas_asr.py yo sample.wav

# unit tests and lint (no network)
pytest -q                        # default run excludes pilot gates
pytest -m pilot                  # release gate before real users (template review done)
ruff check . && ruff format .

# app (once written)
VP_ENV=dev modal serve app/main.py   # dev; log rows go to /logs/dev/ (never pilot evidence)
modal deploy app/main.py         # prod
modal app logs <app-name> | tail -n 20
scripts/warm.sh 90               # pilot session: min_containers=1 for 90 min, then back to 0 (Ctrl+C resets)
scripts/warm.sh off              # reset min_containers to 0 now
modal app stop <app-name>        # stop anything stuck retrying

# audio prep for manual ASR tests
ffmpeg -i note.ogg -ar 16000 -ac 1 note.wav
```

## External services: facts and gotchas

**N-ATLaS LLM (vLLM 0.30.0 on Modal L4)**
- Served model name `natlas`. Max context 4096 here (model card says ~8K).
- `VLLM_USE_FLASHINFER_SAMPLER=0` is required (FlashInfer needs nvcc, which the image lacks).
  `--enforce-eager` keeps startup reliable.
- Cold start ~2 min (measured 134 s); warm intent calls ~2 s. Default `min_containers=0`; for pilot
  sessions use `scripts/warm.sh <minutes>` (never edit the deploy file for this). The page calls
  `GET /api/warm` on load. The app's LLM timeout is 20 s per call.
- vLLM uses `repetition_penalty`; llama.cpp (laptop) uses `repeat_penalty`.

**ASR**: `NCAIR1/Yoruba-ASR`, `NCAIR1/Hausa-ASR`, `NCAIR1/Igbo-ASR`, `NCAIR1/NigerianAccentedEnglish`.
Whisper-small fine-tunes (~967 MB each), gated (accept terms on HF). Input 16 kHz mono.
Quality: Yoruba and Hausa good, Igbo weaker (label it beta). Place names come out spelled by sound.

**Postcode API** (`https://api.postcode.gov.ng`, header `X-API-Key`)
- Docs are partly out of date: **every endpoint needs a key**, and the docs' test postcodes return
  `not_found`. Known-valid code for tests: `LA-11-A12-GN-01` (from reverse geocode of 6.6018, 3.3515).
- Our key is **Lookup level 1 only** (validity). Names and addresses need L2 (requested, pending);
  handle `level_not_granted` gracefully.
- `/v1/search/reverse?lat&lng&max_distance_m=` returns codes only, no names, plus `confidence` and
  `distance_m`. We ask within 50 m first and retry once at 250 m if `found` is false.
- Errors come as `{"error":{"code","message"}}`. Seen live: `auth_required` (no key),
  `level_not_granted` (level above our key). Real responses: `tests/fixtures/postcode/`.
  Responses are wrapped in `data` (`data.found`, `data.unit.postcode`).
- 5 s timeout on every call. Rate limit 600/window (`x-ratelimit-limit`, `x-ratelimit-remaining`
  headers); on `429` wait 2 s and retry once.

## Coding conventions

- Python 3.11 in Modal images. Type hints everywhere; `dataclasses` or Pydantic for payloads.
- FastAPI for HTTP; `httpx.AsyncClient` with explicit timeouts for every outbound call.
- Services sit behind small interfaces so tests use fakes (no network in `pytest`).
- Write the unit test first (or with the code) for every new module; `pytest -q` must pass before moving on.
- Ruff for lint and format: `ruff check . && ruff format .`.
- Log with `print`/`logging` as one JSON line per event; never log coordinates, audio or raw session IDs.
- User-facing strings live only in `app/templates/<lang>.json`, never inline in code.
- **Web page contract.** The web page must match `web/design/prototype.html` exactly: colours, fonts, layout, spacing, components and screen order. Do not redesign it. Use only the phone screen from the Prototype tab (leave out the tabs, trace panel, dashboard and flow view). Keep its `:root` tokens (light and dark), its fonts (Bricolage Grotesque display, Atkinson Hyperlegible body, JetBrains Mono for codes) and its class names. Strings come from `app/templates`, data from `/api/*`. When the page is built, put 360 px screenshots of each screen next to the prototype's in `docs/ui-compare/`. Glyph gaps and the fallback rule are in SPEC.md §1 Front end.
- **Template keys are frozen** (8 Oct, for the native-speaker review). Do not add, rename or remove a
  key without asking the user first. Changing English wording also needs the review sheets regenerated.
  Approved exceptions so far: the 8 `faq_*` keys and `warming_up` (8 Oct); 24 page-label keys `ui_*`,
  `chip`, `conf_*` (9 Oct). The freeze applies again after these.
- Store user text only through `app.privacy.for_storage()` (scrubbed: numbers, phones, emails; capped at
  300 chars). Raw text may be used inside the turn (regex, intent) but never stored.
- Language codes everywhere: `en`, `yo`, `ha`, `ig`.
- Every external failure maps to a friendly, localised message plus a next step.

## LLM prompt conventions

- `temperature: 0` for intent; `0.1` max for replies. `max_tokens` 80 (intent) / 200 (reply).
- Intent: system prompt + few-shot examples in **all four languages** (include a noisy ASR transcript),
  plus `response_format` JSON schema with `intent` enum and `places_mentioned`. Then apply the postcode
  regex and the keyword safety net (`postcode|pósíkòdì|koodu|lamba|...`) before trusting `other`.
- Eval inputs must be held out: never reuse a few-shot example as an eval case.
- Replies: state the language twice (system + end of user message); put facts in the **user** turn under
  `FACTS (use only these)`; cap at ~80 words; never ask the model for a postcode or place name.
- Prompt text lives in `app/services/prompts.py`. Change it only together with `evals/natlas_final_test.py`
  and record the new scores in `evals/results.md`.

## Interaction log schema (validation evidence)

One JSONL row per user turn:
`ts, user_hash, channel(web), lang, input(voice|text|location|choice), transcript, intent,
llm_status(ok|timeout|error|bad_json|null), postcode_found(bool|null), api_status,
latency_ms{asr,llm,api,total}, reply_kind, feedback(yes|no|null), knew_postcode_before(bool|null)`.
No coordinates, raw session IDs or audio; `transcript` is scrubbed and capped. Rows start at consent.

## Definition of done for any change

- `pytest -q` passes, and `ruff check .` is clean.
- Templates exist for all four languages. Strings not yet checked by a native speaker are listed by key
  in that file's `_todo_review` array (the string itself stays displayable); remove the key once reviewed.
  `pytest -m pilot` (not in the default run) fails until every `_todo_review` list is empty; it must pass
  before real users. Reviewers fill `docs/review/<lang>.csv` (`python scripts/review_sheet.py`); apply
  with `python scripts/apply_review.py <lang>`.
- No new runtime dependency on a non-N-ATLAS model or an unapproved external service.
- This file is updated if commands, layout or rules changed; SPEC.md if versions, contracts or budgets changed.

## Future work

The core is channel-agnostic: the orchestrator only sees `Event` and returns `Reply`, and `Event.channel`
already exists. A WhatsApp adapter (Twilio webhook replying inline with TwiML, or the Meta Cloud API) can
be added later as one more thin file in `app/channels/` without touching the orchestrator. It is out of
scope for NAIC 2026: the Twilio trial did not forward voice notes or locations and the Meta business
account is locked. The Twilio echo prototype is kept in `archive/twillo_echo.py`.

## Changelog

- 2026-10-08: Web-only scope. PS2 delivery channel is a low-bandwidth mobile application. WhatsApp
  (Twilio, Meta) moved to Future work; `deploy/twillo_echo.py` moved to `archive/`. Live-model evals
  moved from `tests/` to `evals/` (scores in `evals/results.md`). vLLM pinned to 0.30.0. Reverse geocode
  radius 250 m, 5 s Postcode API timeout. New `voice-postcode` secret with `POSTCODE_API_KEY` and
  `HASH_SALT`. `knew_postcode_before` asked once per user after the first postcode result. Tests first.
- 2026-10-08: `knew_postcode_before` moved to right after language choice, before any postcode (skippable
  -> null), to avoid biasing the answer. Reverse geocode tries 50 m, then 250 m once. `states.json` has
  the 11 codes named in the official API docs. Live API responses (3 Oct) replace the reconstructed test
  fixtures. Superseded root scripts `natlas_{llm,text,local}_test.py` deleted.
- 2026-10-08: Templates for en/yo/ha/ig (en final; yo/ha/ig drafts, all translated keys in `_todo_review`).
  `app/store.py`: user hashing, sessions, JSONL log with one file per container per day.
- 2026-10-08: `pytest -m pilot` gate for template review; Definition of done uses the `_todo_review` list.
- 2026-10-08: Orchestrator with service Protocols (`app/services/interfaces.py`). Logging starts at
  consent; declining deletes the session. LLM failure degrades to the keyword safety net.
- 2026-10-08: Onboarding is language -> consent -> knew_before -> ready. `app/privacy.py` scrubs PII
  before storage (300-char cap). `llm_status` in the log. Anonymous daily decline counter. `ask_code`
  offers code or location. Template keys frozen; review sheets in `docs/review/`.
- 2026-10-08: `web/design/prototype.html` is the design source of truth (web page contract above).
- 2026-10-08: `prompts.py`, `llm.py` (guard), fact sheets (yo/ha/ig in the review flow), evals rebuilt on
  `prompts.py` with 40 + 12 held-out cases; results in `evals/results.md`.
- 2026-10-08: FAQ routing replaces generated explain answers (`EXPLAIN_MODE=faq`). 20 s LLM timeout +
  `warming_up`; `/api/warm`; `scripts/warm.sh`. Self-hosted subset fonts in `web/fonts/`.
- 2026-10-09: `asr.py` (pinned revisions, ffmpeg pipes, 20 s limit, silence skip), `channels/web.py`,
  `main.py` (Modal wiring, 30-min TTL sweep for unconsented sessions, `VP_ENV=dev` log isolation).
- 2026-10-09: `web/index.html` from the prototype; 24 page-label keys (approved); street/name rule; Postcode
  `auth` errors kept apart from not-found; screenshots in `docs/ui-compare/`.
