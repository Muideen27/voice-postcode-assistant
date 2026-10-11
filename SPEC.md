# SPEC.md: stack, versions, constraints and expected outputs

Companion to CLAUDE.md. CLAUDE.md says how we work; this file says exactly what we build with and
what each part must return. Any change to a version, contract or budget here needs a matching code
change and a note in the changelog at the bottom.

Status markers: **[verified]** = seen working in our own tests or logs, **[pin]** = must be confirmed
and written in before the first app deploy, **[target]** = budget we design for, measured in the pilot.

---

## 1. Stack and versions

### Delivery channel

PS2 delivery channel: **low-bandwidth mobile application**, delivered as a mobile web page (plain
HTML/JS, < 50 KB) served over HTTPS by the Modal app. Web is the only channel in scope (see Future work).

### Runtime platform

| Component | Version | Status | Notes |
|---|---|---|---|
| Modal (hosting, GPUs, secrets, storage) | client 1.6.1 (laptop) | [verified] | Workspace `muideen27`, Starter plan, spend cap $30 |
| Modal image base | `debian_slim`, Python **3.11** | [verified] | All server code targets 3.11 |
| Laptop dev env | Ubuntu 24.04, Python **3.12** venv | [verified] | Code must run on both 3.11 and 3.12 |
| GPU for LLM | NVIDIA **L4** (24 GB) | [verified] | N-ATLaS BF16 uses ~15 GiB; 4.4 GiB left for KV cache |
| GPU for ASR | NVIDIA **L4**, same class | [target] | Separate container; merge with LLM only if memory allows |
| ffmpeg | Debian package in image; 6.1.1 on laptop | [verified laptop] | Converts WebM/Opus, MP4/AAC, OGG to 16 kHz mono WAV |

### Models (the only AI models allowed at runtime)

| Model | Repo | Status | Notes |
|---|---|---|---|
| LLM | `NCAIR1/N-ATLaS` (Llama-3 8B fine-tune, BF16) | [verified] | Served as `natlas` |
| ASR Yoruba | `NCAIR1/Yoruba-ASR` | [verified] | Whisper-small fine-tune, ~967 MB |
| ASR Hausa | `NCAIR1/Hausa-ASR` | [verified] | |
| ASR Igbo | `NCAIR1/Igbo-ASR` | [verified access] | Weaker quality, label beta |
| ASR English | `NCAIR1/NigerianAccentedEnglish` | [verified access] | |

Pinned ASR revisions (8 Oct 2026, loaded with `revision=` in `app/services/asr.py`) [verified]:
Yoruba `d1ae7b8b79c2ccd547d8761effe5057433f3fc7f`, Hausa `e635b9eda29060c6114c8f4d8b2d903f5c83a44a`,
Igbo `180732299d5cba3dc8b289260ac84b7838bb3954`, English `3c52c6e6c9ec508014a7b9db6a42b503b8930dff`.
N-ATLaS LLM revision: not pinned yet (vLLM loads `main`). [pin]

### Python packages

Versions below are what Modal's mirror installed in our working images on 4 to 8 Oct 2026. Pin exactly.

| Package | Version | Status | Used for |
|---|---|---|---|
| vllm | 0.30.0 | [verified] (from `serve.log`) | LLM serving; pinned in `deploy/natlas_serve.py` |
| torch | 2.14.1 | [verified] | ASR inference |
| transformers | 5.18.0 | [verified] | Whisper ASR (`WhisperForConditionalGeneration`) |
| huggingface_hub | 1.33.0 | [verified] | Model download, revision pinning |
| accelerate | 1.15.0 | [verified] | Model loading |
| fastapi | 0.142.4 | [verified] | HTTP app (web) |
| uvicorn | 0.54.0 | [verified] | Pulled in by `fastapi[standard]` |
| pydantic | 2.13.5 | [verified] | Payload models |
| httpx | 0.28.1 | [verified] | Outbound calls (Postcode API, LLM) |
| python-multipart | 0.0.32 | [verified] | Audio upload (`/api/voice`) |
| librosa | 1.0.0 | [verified laptop] | Audio loading for ASR |
| soundfile | 0.14.0 | [verified laptop] | Audio I/O |
| pytest | 9.1.1 | [verified laptop] | Unit tests, dev only |
| ruff | 0.16.10 | [verified laptop] | Lint and format, dev only |

### External services

| Service | Endpoint | Auth | Status | Limits we design for |
|---|---|---|---|---|
| Postcode API (NIPOST gateway) | `https://api.postcode.gov.ng` | `X-API-Key` (test key) | [verified] | Lookup **L1 only**; 600 req/window; 5 s timeout |
| Hugging Face Hub | model downloads at build time only | `HF_TOKEN` secret | [verified] | Never called per request |

### Secrets (Modal)

| Secret | Keys | Used by |
|---|---|---|
| `huggingface` | `HF_TOKEN` | Model downloads |
| `natlas-api` | `NATLAS_API_KEY` | vLLM server and LLM client |
| `voice-postcode` | `POSTCODE_API_KEY`, `HASH_SALT` | App: Postcode client, user hashing |

### Front end

| Item | Choice | Constraint |
|---|---|---|
| Web page | Plain HTML + vanilla JS + inline CSS, no framework, no build step | HTML + CSS + JS < 50 KB; fonts < 120 KB total |
| Fonts | Self-hosted woff2 in `web/fonts/`, built by `scripts/build_fonts.py` | `Cache-Control: public, max-age=31536000, immutable` |
| Audio capture | `MediaRecorder` (Opus/WebM on Android, MP4/AAC on iOS) | Max 20 s per recording |
| Location | `navigator.geolocation.getCurrentPosition`, `enableHighAccuracy: true`, timeout 15 s | HTTPS only |
| Browsers supported | Chrome for Android 100+, Samsung Internet 20+, Safari iOS 15+ | Test on one low-end Android phone |
| Design | `web/design/prototype.html` | Source of truth; see contract below |

**First screen.** As in the prototype: "Choose your language" title and intro line in the browser's
language (`navigator.language` if en/yo/ha/ig, else English), switching once a language is picked;
the four language names in their own languages (prototype order en, yo, ha, ig), Igbo marked with the
`ui_beta` chip, the N-ATLaS attribution below. Consent, "did you know" and `ask_code` screens are built
only from prototype parts. Page labels are template keys `ui_*`, `chip`, `conf_*` (reviewed via
`docs/review/ui_<lang>.csv`).

**Tabs and pilot dashboard.** The prototype's tab bar sits above the app with two tabs: the app (label
`ui_bar_title`, default) and "Pilot dashboard" (English only). Tab, KPI, bar-card, table and banner styles
are copied verbatim from the prototype. The dashboard is fetched only when its tab is opened and shows:
KPIs Real interactions (PS2 minimum 50) · Left with a valid postcode (% of location + validate turns) ·
Did not know their postcode before (% of knew_before = false) · Said it helped (% yes); cards
Interactions by language · Said it helped, by language · What people asked for (My postcode / Explain it
/ Check a code / Other) · Median response time, location vs voice; a status line "Official postcode
database today: OK | no data | unreachable" from today's canary; the last 10 rows (time WAT, language,
input, intent, postcode outcome, latency, feedback). Before `PILOT_START` (env, ISO time, set at deploy)
it shows zeros and "—". No sample data anywhere.

**Footer.** Text attribution only (no image).

**Cold start on the page.** A voice or text turn that needs a cold model waits on the progress screen with
`warming_up_long` ("Waking up the language model, about 2 minutes, the first time only"), polling
`/api/warm`, up to 180 s, then sends. Voice waits only for ASR (a spoken postcode never needs the LLM); if the
reply is `warming_up` it waits for the LLM and re-sends the same recording once. Typed text containing a
postcode and location never wait.

**Web page contract.** The web page must match `web/design/prototype.html` exactly: colours, fonts, layout, spacing, components and screen order. Do not redesign it. Use only the phone screen from the Prototype tab (leave out the tabs, trace panel, dashboard and flow view). Keep its `:root` tokens (light and dark), its fonts (Bricolage Grotesque display, Atkinson Hyperlegible body, JetBrains Mono for codes) and its class names. Strings come from `app/templates`, data from `/api/*`. When the page is built, put 360 px screenshots of each screen next to the prototype's in `docs/ui-compare/`.

**Glyph coverage** (checked 8 Oct 2026 against the Google Fonts files the prototype loads, all subsets):

| Font | Missing of ẹ ọ ṣ à á è é ì í ò ó ù ú ń ɓ ɗ ƙ ƴ ị ụ ṅ | Also missing |
|---|---|---|
| Atkinson Hyperlegible 400/700 (body) | ẹ ọ ṣ ɓ ɗ ƙ ƴ ị ụ ṅ | uppercase Ẹ Ọ Ṣ Ɓ Ɗ Ƙ Ƴ Ị Ụ Ṅ; combining dot below U+0323 |
| Bricolage Grotesque 500/700 (display) | ṣ ɓ ɗ ƙ ƴ ṅ | uppercase Ṣ Ɓ Ɗ Ƙ Ƴ Ṅ |
| JetBrains Mono 500/700 (codes) | ṣ ɓ ɗ ƙ ƴ ṅ | uppercase Ṣ Ɓ Ɗ Ƙ Ƴ Ṅ |

All three have à á è é ì í ò ó ù ú ń and the combining grave/acute. **Atkinson Hyperlegible Next** was
checked as a replacement (Google Fonts subsets and the upstream google/fonts file): it misses the same
letters, so the body font stays Atkinson Hyperlegible.

**Self-hosted fonts** (`web/fonts/`, built by `scripts/build_fonts.py`; 5 files, 103,680 bytes = 101.3 KiB):

| File | Font, weights | Subset | Size |
|---|---|---|---|
| `atkinson-400.woff2`, `atkinson-700.woff2` | Atkinson Hyperlegible 400, 700 | Latin, Latin Ext. Additional, ń ɓ ɗ ƙ ƴ (+caps), combining marks, punctuation | 10.0 + 10.2 KB |
| `bricolage.woff2` | Bricolage Grotesque, variable wght 500–700, opsz 12–48 | same | 60.1 KB |
| `jetbrains-700.woff2` | JetBrains Mono 700 (the phone screen uses mono only at 700) | ASCII + "·" (it only renders codes) | 16.3 KB |
| `fallback-sans.woff2` | Noto Sans, wght 400–700 | only ẹ ọ ṣ ɓ ɗ ƙ ƴ ị ụ ṅ, their capitals, U+0300/0301/0323 | 4.7 KB |

Measured page weight (9 Oct): `index.html` (HTML + CSS + JS) **19.6 KB raw, 6.5 KB gzip**; strings JSON
2.1–2.5 KB gzip per language (4 fetched on load); fonts actually downloaded by an English user 96.6 KiB
(the fallback, 4.7 KiB, loads only when a Yorùbá/Hausa/Igbo letter needs it).

- Bricolage's optical-size axis is limited to 12–48 (the prototype's largest display text is 38 px), so it
  renders the same as the prototype's 12–96 range; this saves 9 KB.
- Fallback: `fallback-sans` is declared as a second `@font-face` for the body and display families with
  `unicode-range` set to exactly its letters, so it is used only where Atkinson/Bricolage lack a letter.
  Coverage checked after subsetting: no required letter is missing. No fallback is needed for mono.

---

## 2. Global constraints

1. Only `NCAIR1/*` models at runtime. No other LLM, ASR, TTS or translation service.
2. Facts (postcodes, validity, segment meanings) come from the Postcode API and templates, never the LLM.
3. Languages: `en`, `yo`, `ha`, `ig`. The user picks one; it is passed explicitly everywhere.
4. Privacy: no NIN, names, contact details, coordinates or audio stored.
   IDs = `sha256(HASH_SALT + channel + ":" + session_id)`.
5. Licence: attribution shown in welcome and footer; < 1,000 active users per 30 days.
6. Budget: Modal spend ≤ $30 for October. GPUs warm only during scheduled sessions.
7. Every outbound call has a timeout and a localised fallback message.

### Latency budgets [target]

| Path | Warm | Cold (GPU asleep) | Hard limit |
|---|---|---|---|
| Page (GET /) | ≤ 2 s (one CPU web container always on; measured 1.1–1.3 s) | — | — |
| Location → postcode reply | ≤ 3 s | ≤ 3 s (no GPU used) | 10 s |
| Text → reply | ≤ 5 s | ≤ 20 s, then safety net or `warming_up` | 20 s per LLM call |
| Voice (≤ 15 s clip) → reply | ≤ 12 s | ASR cold start + 20 s LLM limit | see §3.3 |

Cold LLM GPU (cold start measured at ~2 min): the LLM call times out after **20 s**. The orchestrator logs
`llm_status=timeout`, applies the keyword safety net, and if the net finds nothing answers with the
`warming_up` template ("still waking up, try again in a minute"). To avoid most cold turns:
`GET /api/warm` (called once by the page on load) starts the GPU in the background, and pilot sessions run
`scripts/warm.sh <minutes>`, which sets `min_containers=1` for that window only (default stays 0).

---

## 3. Component contracts and expected outputs

### 3.1 `Event` (the web channel produces this)

```python
@dataclass
class Event:
    user_hash: str                      # sha256(HASH_SALT + "web:" + session id)
    channel: Literal["web"]             # only "web" for now; see Future work
    type: Literal["text", "voice", "location", "choice", "feedback"]
    lang: Literal["en", "yo", "ha", "ig"] | None
    text: str | None = None             # typed text or menu digit
    audio: bytes | None = None          # raw upload, any of webm/mp4/ogg/wav
    audio_mime: str | None = None
    lat: float | None = None            # never persisted
    lng: float | None = None
```

### 3.2 `Reply` (the orchestrator returns this; the channel renders it)

```python
@dataclass
class Reply:
    kind: Literal["welcome", "declined", "menu", "language_menu", "postcode", "validation", "answer",
                  "ask_location", "ask_knew_before", "ask_code", "error", "thanks"]
    lang: str
    text: str                           # final localised text, ≤ 600 chars
    postcode: str | None = None         # "LA-11-A12-GN-01"
    segments: list[tuple[str, str]] | None = None   # [("LA", "Lagos State"), ...] labels from templates
    confidence: Literal["high", "medium", "low"] | None = None
    transcript: str | None = None       # shown to user as "We heard: ..."
    distance_m: float | None = None     # reverse-geocode distance, for the confidence chip
```

Example expected output for a location in Ikeja (en):

```json
{"kind":"postcode","lang":"en","postcode":"LA-11-A12-GN-01","confidence":"high",
 "segments":[["LA","Lagos State"],["11","your Local Government Area"],["A12","your district"],["GN","your area"],["01","your building"]],
 "text":"Your postcode is LA 11 A12 GN 01.\nLA = Lagos State\n11 = your Local Government Area\nA12 = your district\nGN = your area\n01 = your building\nDid this help? Tap 1 for yes, 2 for no."}
```

### 3.3 ASR service

- Call: `ASR.transcribe(lang, audio: bytes, mime: str) -> AsrResult`
- Input: ≤ 20 s and ≤ 2 MB of audio, any of WebM/Opus, MP4/AAC, OGG/Opus, WAV. Rejected otherwise.
- Processing: ffmpeg → 16 kHz mono WAV → model for `lang` (all four loaded once per container).
- Output:
```json
{"text":"ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi ...","lang":"yo","model":"NCAIR1/Yoruba-ASR",
 "audio_seconds":10.8,"latency_ms":2400}
```
- Empty or near-silent audio → `text: ""` and the orchestrator replies "Couldn't hear that clearly".
- Measured (8 Oct, L4): cold start 76 s (45 s loading the four models), warm 2–3 s for 10–19 s clips.
  The per-turn ASR timeout is 20 s (→ `timeout_retry`); `/api/warm` also spawns an ASR container.
- Audio is decoded through ffmpeg pipes and never written to disk; only 16-bit PCM goes to the GPU.

### 3.4 LLM: intent

- Endpoint: `POST {NATLAS_URL}/v1/chat/completions` (`Authorization: Bearer NATLAS_API_KEY`), model
  `natlas`, `temperature: 0`, `max_tokens: 80`, `repetition_penalty: 1.12`, `response_format: json_schema`.
  Prompt: system prompt naming the user's language + few-shot pairs (≥ 2 per language, one noisy ASR
  transcript each) in `app/services/prompts.py`.
- Timeout per LLM call: **20 s** read, 5 s connect, **no retry inside a user turn** (see §2 cold start).
- Output (always schema-valid):
```json
{"intent":"explain_postcode","faq_id":"place_name_no","confidence":0.9,"places_mentioned":[]}
```
- `faq_id` ∈ `what_is | parts | since_when | get_mine | check_one | place_name_no | privacy | who_built |
  none`; meaningful only when `intent` is `explain_postcode` (the client sets it to null otherwise).
  Few-shot: 20 pairs, every language and every `faq_id` covered; eval cases stay held out.
- `confidence` ∈ [0, 1]; below **0.5** the orchestrator treats the intent as `other` (then the net).
  `places_mentioned` is never used as a fact. Unparseable or off-schema output → `LlmError("bad_json")`;
  timeout → `timeout`; HTTP/transport errors → `error` (logged as `llm_status`).
- `intent` ∈ `get_my_postcode | validate_postcode | explain_postcode | greeting | other`.
- Order: (1) a postcode is found in the text (see below) → `lookup` directly, **the LLM is not called**;
  (2) otherwise classify; if the LLM fails or times out, treat the intent as `other`;
  (3) intent `other` → keyword safety net on lower-cased, diacritic-free text: a validation word
  (`valid|correct|check|real|confirm|tona|sayewo|daidai|ingantacciya|duba|ziri ezi|lelee`) →
  `validate_postcode`, else a postcode word (`postcode|post code|posikodi|koodu|lamba|adiresi|address`) →
  `get_my_postcode`; (4) still `other` → menu. `validate_postcode` with no code in the text → `ask_code`.
  (5) `get_my_postcode` and the text names a street, road or "name" (`street|road|avenue|crescent|name|
  opopona|oruko|titi…|suna(n)|okporo uzo|aha`, folded) → `explain_postcode` + `place_name_no`
  (`resolve_route`, shared with the evals).
  Steps (1)–(3) are one pure function, `app.orchestrator.resolve_intent`, which the evals import.
- Postcode search (in `app/services/postcode.py`, `find_postcode(text)`): case-insensitive, **unanchored**,
  segments separated by `-`, spaces or nothing:
  `\b([A-Z]{2})[\s-]?(\d{2})[\s-]?([A-Z0-9]{3})[\s-]?([A-Z]{2})[\s-]?(\d{2})\b`. Matches are normalised
  to upper case with hyphens (`la 11 a12 gn 01` → `LA-11-A12-GN-01`).
- Acceptance: on `evals/natlas_final_test.py` (40 held-out cases, 10 per language, `evals/cases.py`),
  routed intent accuracy (after regex + safety net) **≥ 85% overall**; 100% schema-valid; warm p50 ≤ 3 s.

### 3.5 Explain: FAQ routing (production) and generate mode (off)

`EXPLAIN_MODE=faq` (default, production): no free-text generation. `explain_postcode` + `faq_id` → the
template `faq_<faq_id>` (en final; yo/ha/ig reviewed via `docs/review/faq_<lang>.csv`). Reply kinds:
`get_mine`, `place_name_no` → `ask_location` (location button); `check_one` → `ask_code`; others → `answer`
with feedback. `faq_id` none → `explain_fallback` + menu (`reply_kind = template_fallback`). Each FAQ answer
is ≤ 60 words, facts only from the fact sheet (privacy answer from the privacy rules); `faq_who_built`
carries the N-ATLaS attribution and "Postcode data from the Nigeria Postcode API". Log `reply_kind =
faq_<faq_id>`. Acceptance: FAQ routing eval (20 cases, 5 per language) reported in `evals/results.md`.

`EXPLAIN_MODE=generate` (kept for evals, **off in production**): the LLM answers from the fact sheet.

- `temperature: 0.1`, `max_tokens: 200`; language stated in system prompt and at the end of the user turn;
  facts under `FACTS (use only these)` in the user turn.
- Expected output: ≤ 80 words, in the requested language, no URLs, no numbers or place names that are not
  in FACTS. If a postcode is in FACTS, the reply contains it character for character.
- FACTS = `data/fact_sheet_<lang>.md` without its `review:` front matter. Allowed content only: the format
  AA-99-H77-BB-55 and its parts, the example LA-11-A12-GN-01, live since 1 Oct 2026, get = share location,
  check = say or type it, no postcode from a place name alone. yo/ha/ig sheets are reviewed through the same
  The fact sheets are the source for writing the FAQ templates; they are sent to the model only in
  generate mode and are no longer in the review sheets or a pilot gate.
- Guard (`app.services.llm.guard`): discard the reply if it has a URL or domain, a postcode not in FACTS,
  more than 120 words, a number not in FACTS, a Nigerian place name not in FACTS, a capitalised word that
  is not sentence-initial and not in FACTS, the user's question or a small allowlist (language and country
  names, LGA, NIN, months), or (yo/ha/ig) more than 30% common English words. The orchestrator then sends the `explain_fallback` template and logs
  `reply_kind = "template_fallback"`. The orchestrator re-checks URLs and postcodes (second guard).
- Acceptance: no invented postcode or place name in any explain answer in the evals.

### 3.6 Postcode client

Every call: header `X-API-Key`, **5 s timeout**. API responses are wrapped in `data`.

| Function | Call | Expected output |
|---|---|---|
| `reverse(lat, lng)` | `GET /v1/search/reverse?lat&lng&max_distance_m=50`, then once with `=250` if `found` is false | `{"found":true,"postcode":"LA-11-A12-GN-01","display":"LA 11 A12 GN 01","confidence":"high","distance_m":9.2}` or `{"found":false}` |
| `lookup(code)` | `GET /v1/lookup?code=&level=1` | `{"postcode":"LA-11-A12-GN-01","valid":true,"status":"valid"}` or `valid:false, status:"not_found"` |
| `segments(code)` | local split + `data/states.json` | `[("LA","Lagos"),("11",None),("A12",None),("GN",None),("01",None)]` |

- `segments()` returns raw codes plus the state name only when the state code is in `data/states.json`
  (else `None`). The orchestrator turns each segment into a label from the templates (§3.2 example).
- `data/states.json` holds **documented codes only**: AK, BA, EB, EK, EN, FC, JI, KN, LA, NI, OG, each
  paired with its state name in the official API docs (docs.postcode.gov.ng "Test postcodes" table and
  widget/format examples, compiled 1 Oct 2026). Any other state code is shown as the code alone, never guessed.
- Response shapes are [verified]: live responses from 3 Oct 2026 are in `tests/fixtures/postcode/`
  (re-record with `scripts/record_postcode_fixtures.py`). Live reverse bodies also carry `coordinate`,
  `area`, `district`, `state`, `depth`, `radius_m` (unused). Lookup also returns `verified` (unused).
  200s carry `x-ratelimit-limit: 600` and `x-ratelimit-remaining`.

Errors arrive as `{"error":{"code","message"}}`. Mapping: `invalid_api_key`, `auth_required` or `401/403`
→ **`auth`** error (alert with the API code; generic user message; logged `api_status = "auth:<code>"`).
An auth failure is never shown or logged as "no postcode here" / "not found" (a 404 carrying an auth code
is auth, not not-found); `402` → credits error; `level_not_granted` → its own error kind (we only
call level 1, so it signals a config bug); `429` → wait and retry once after 2 s; timeout (5 s) →
"service is slow, try again"; `404` on lookup → not found.

**Data canary** (`app/canary.py`): at every web container start (background task) and every 30 minutes
(`postcode_canary` scheduled function), look up LA-11-A12-GN-01 at level 1 and log one JSON line
`{"canary": "valid|not_found|auth|error", "ts": ...}`. Daily counts and the last result go to the
`voice-postcode-canary` Dict (`{"YYYY-MM-DD": {"valid": n, "not_found": n, "auth": n, "error": n, "last",
"last_ts"}}`), next to the declines counter; `export_log.py` reports them per day. It never touches users
or the interaction log.

Not-found wording never blames the user or the location: `postcode_not_found` = "The official postcode
database has no postcode for this spot yet…", `validation_not_found` = "{display} is not in the official
postcode database yet…".

### 3.7 Web endpoints

| Route | Request | Response |
|---|---|---|
| `GET /` | none | `index.html` (HTML + CSS + JS < 50 KB) |
| `GET /fonts/<file>.woff2` | none | font file, `Cache-Control: public, max-age=31536000, immutable` |
| `GET /api/strings/<lang>` | none | every template string for that language (the page renders only these) |
| `POST /api/location-denied` | `{"session"}` | `Reply` (`error`, `location_denied`): geolocation refused or failed |
| `GET /api/stats` | none | pilot dashboard JSON (KPIs, bars, last 10 rows, today's canary); real log rows from `PILOT_START` only, `/logs/dev/` excluded; 60 s cache; never transcripts or user hashes |
| `GET /api/warm` | none | `{"llm": bool, "asr": bool}` (readiness, ~1 s warm, a few s while cold); if either is cold, starts both warm-ups in the background (not again within 120 s). The page calls it on load and polls while something is cold. |
| `POST /api/language` | `{"session":"<uuid>","lang":"yo"}` | `Reply` (`welcome` with consent for a new user, else `menu`) |
| `POST /api/consent` | `{"session","agree":true\|false}` | `Reply` (`ask_knew_before`, or `declined`) |
| `POST /api/location` | `{"session","lat","lng","accuracy_m"}` | `Reply` (postcode) |
| `POST /api/voice` | multipart: `session`, `audio` file | `Reply` (any kind) |
| `POST /api/text` | `{"session","text"}` (≤ 500 chars) | `Reply` |
| `POST /api/feedback` | `{"session","helpful":true}` | `Reply` (thanks) |
| `POST /api/feedback` | `{"session","knew_before":true\|false\|null}` (null = skipped) | `Reply` (menu) |

`session` is a random UUID kept in the browser; the server hashes it before use.

The first screen (`GET /`) is the language menu: the four language names, each in its own language, and
the N-ATLaS attribution, nothing else. It needs no API call. Rendering rules for the page: `welcome` →
consent and decline buttons; `ask_knew_before` → yes / no / skip; `ask_code` → **both** a location button
and a text box; `postcode`, `validation`, `answer` → feedback buttons.

### 3.8 Interaction log

One JSONL line per user turn in a Modal Volume at `/logs/interactions-YYYY-MM-DD-<container>.jsonl`
(date in WAT; one file per container so two containers never append to the same file; the Volume is
committed after each row). `app/store.py` `LogRow` enforces the field list and rejects any `user_hash`
that is not a sha256 hex digest:

```json
{"ts":"2026-10-10T14:52:03+01:00","user_hash":"7f3a…","channel":"web","lang":"yo","input":"voice",
 "transcript":"ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi","intent":"get_my_postcode","llm_status":"ok","postcode_found":null,
 "api_status":null,"latency_ms":{"asr":2400,"llm":2100,"api":null,"total":4700},
 "reply_kind":"ask_location","feedback":null,"knew_postcode_before":null}
```

`knew_postcode_before` is asked once per user, right after consent (language → consent → this question) and **before any postcode
is shown** (asking after a result would bias it). It is skippable (→ null) and is set only on the row of
the turn that answers it (null elsewhere).

Sessions live in a `modal.Dict` keyed by `user_hash`, stored as plain dicts:
`{stage: "consent"|"knew_before"|"ready", lang, awaiting_feedback, turns}`. Stage `new` (language menu)
is never stored: a session is written only once a language is chosen. No postcode, coordinates or text are
kept in the session. Declining consent deletes the session.
Unconsented sessions (stage `consent`) expire after **30 minutes** without a reply: `main.py` deletes them
(TTL by a `created_ts` check on read plus a periodic sweep). Consented sessions follow the Modal Dict's
own retention.

Declines: an anonymous daily counter in its own `modal.Dict`, `{"YYYY-MM-DD": count}` (WAT), with no
hash, session or text. `scripts/export_log.py` reports it alongside the log summary.

Logging rule: one row per user turn **after consent**. The language menu, welcome and a declined consent
write nothing. `transcript` holds the ASR text for voice and the typed text for text input, always passed
through `app.privacy.for_storage()`: postcodes kept; emails → `[EMAIL]`; Nigerian phones (`+234…`,
`0[789][01]…`) → `[PHONE]`; any other run of 7+ digits (NIN, BVN, account numbers) → `[NUMBER]`; then
capped at 300 characters. Names are not redacted (not reliable), which is why the cap exists.
`llm_status` is `ok|timeout|error|bad_json`, or null when the LLM was not called. On LLM failure the
logged `intent` is `other` (routing still uses the keyword net).
`reply_kind` is `Reply.kind`, except `template_fallback` when the explain answer came from the template.

`scripts/export_log.py` must glob `interactions-*.jsonl` across all days and containers, merge the rows,
sort them by `ts`, and drop duplicates on `(ts, user_hash)` (top-level files only; `/logs/dev/` is ignored).
`--since <ISO>` drops rows before the pilot start. Output: `docs/validation/interactions.csv` (one row per
turn, latency flattened) and `docs/validation/summary.md`: interactions, unique users, by language, by input
type, intent mix, feedback yes/no, knew-before split, latency p50/p95 per stage, declines per day, canary
results per day.

---

## 4. Acceptance checklist (before real users)

- [ ] Location path returns `LA-11-A12-GN-01` for `6.6018, 3.3515` in all four languages.
- [ ] Voice path: one recorded clip per language returns a non-empty transcript and a sensible `Reply`.
- [ ] Text path: the three demo sentences (postcode check, Yoruba request, Hausa question) route correctly.
- [ ] Invalid code `LA-11-W06-TC-10` returns "not found", never "valid".
- [ ] LLM guard rejects a reply that contains a URL or an unknown postcode (unit test with a fake LLM).
- [ ] Web page under 50 KB, works on a low-end Android phone over mobile data.
- [ ] Cold GPU: the page shows progress and gets a reply (or a retry message) within 180 s.
- [ ] Log rows contain no coordinates, raw session IDs or audio; transcripts are scrubbed (NIN, phone, email).
- [ ] Attribution visible on welcome screen and footer.
- [ ] Every template string reviewed by a native speaker (`_todo_review` empty in yo/ha/ig).
- [ ] `pytest -m pilot` passes (all `_todo_review` lists empty).

---

## Future work

The core is channel-agnostic: `Event` → orchestrator → `Reply`, with `Event.channel` already in place.
A WhatsApp adapter (Twilio webhook with inline TwiML replies, or the Meta Cloud API) can be added later as
a thin `app/channels/` file plus its own secret and latency budget, without changing the orchestrator.
It is out of scope for NAIC 2026 (Twilio trial did not forward voice or location; Meta account locked).
The Twilio echo prototype is kept in `archive/twillo_echo.py`.

---

## Changelog

- 2026-10-08: first version.
- 2026-10-08: Web-only scope; PS2 delivery channel = low-bandwidth mobile application. Removed the Twilio
  channel contract (old §3.8), `twilio` package, WhatsApp latency columns and "waking up" message; web cold
  GPU waits up to 180 s with progress. WhatsApp moved to Future work. vllm pinned 0.30.0; librosa,
  soundfile, pytest, ruff pinned to `requirements.txt` values. Reverse radius 50 → 250 m; 5 s timeout on
  every Postcode API call; postcode regex unanchored, case-insensitive, normalised. `states.json` holds
  verified codes only. `HASH_SALT` in new `voice-postcode` secret. `knew_postcode_before` asked once after
  the first postcode result (`Reply.kind` `ask_knew_before`). Evals moved to `evals/`.
- 2026-10-08: `knew_postcode_before` asked right after language choice, before any postcode, skippable.
  `reverse()` tries 50 m then 250 m once. `states.json` = 11 codes from the official API docs. Postcode API
  shapes verified from live responses (3 Oct 2026); error envelope and `auth_required` /
  `level_not_granted` mapping documented.
- 2026-10-08: Log file per container per day (`interactions-YYYY-MM-DD-<container>.jsonl`), Volume commit
  per row; session fields defined; review marker is the `_todo_review` key list in each template file.
- 2026-10-08: `export_log.py` merge/sort/dedupe contract. Pilot gate: `pytest -m pilot` (excluded from
  the default run) fails while any `_todo_review` list is non-empty.
- 2026-10-08: Orchestrator contract: `Reply.kind` adds `welcome`, `declined`, `ask_code`; session uses
  `stage`; LLM failure falls back to the keyword net; validation keywords added to the net; logging starts
  at consent. Segment template strings are labels only; lines are built as `<CODE> = <label>`.
- 2026-10-08: Onboarding order language → consent → knew_before; new `POST /api/consent`; `/api/language`
  returns the welcome. PII scrub + 300-char cap on stored text. `llm_status` added to the log schema.
  Anonymous daily decline counter. `ask_code` shows location button and text box. Template keys frozen.
- 2026-10-08: LLM contracts: intent schema adds `confidence` (< 0.5 → other); 150 s per-call timeout, no
  retry; fact sheet content rules; guard rules (URL, postcode, number, place, length, wrong language).
  Eval acceptance: ≥ 85% routed intent accuracy on 40 held-out cases.
- 2026-10-08: Explain becomes FAQ routing (`faq_id` in the intent schema, 8 FAQ templates, `EXPLAIN_MODE`
  default `faq`; generate mode kept, off). Guard rejects unknown capitalised words. LLM timeout 20 s with
  `warming_up` template; `GET /api/warm`; `scripts/warm.sh`. Fonts self-hosted and subset;
  budget HTML+CSS+JS < 50 KB, fonts < 120 KB. Fact sheets out of the review flow.
- 2026-10-09: ASR revisions pinned; ASR cold/warm timings. New routes `/api/strings/<lang>` and
  `/api/location-denied`. Dev runs (`VP_ENV=dev`) log to `/logs/dev/`.
- 2026-10-11: Footer image slot and `ui_footer_alt` removed (text attribution only). `/api/warm` returns
  readiness; page holds cold turns with `warming_up_long`. Submission docs and PDF build scripts.
- 2026-10-11: `/api/stats` + dashboard tab (`PILOT_START`), `/assets/` footer slot (`ui_footer_alt`),
  startup rule (background jobs with timeouts, canary 15 s cap), web `min_containers=1` (cold CPU start
  6-14 s measured, memory snapshot did not help). Secrets: re-deploy after re-creating a secret.
- 2026-10-09: Data canary (start + 30 min, daily Dict); not-found wording; export_log outputs
  (`docs/validation/interactions.csv`, `summary.md`, `--since` for the pilot start); `warm.sh` warms LLM and
  ASR. Deployed at https://muideen27--voice-postcode-web.modal.run.
- 2026-10-09: Postcode `auth` error kind (`invalid_api_key`, `auth_required`, 401/403) never reads as not
  found. `Reply.distance_m`. Street/name rule → `faq_place_name_no`. Page labels as template keys (24:
  `ui_*`, `chip`, `conf_*`), first-screen rules, measured page weight; JetBrains Mono 500 dropped (unused).
- 2026-10-08: Web page contract: match `web/design/prototype.html` exactly (phone screen only). Glyph
  coverage table and unicode-range fallback rule. Open question on font transfer size vs the 50 KB budget.
  30-minute TTL for unconsented sessions (implemented in `main.py`).
