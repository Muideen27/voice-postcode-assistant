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

Pin model revisions: before the pilot, record each repo's commit hash (`huggingface_hub.HfApi().model_info(repo).sha`)
here and load with `revision=<sha>` so a repo update cannot change behaviour mid-pilot. [pin]

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
| Web page | Plain HTML + vanilla JS + inline CSS, no framework, no build step | Total transfer < 50 KB before audio |
| Audio capture | `MediaRecorder` (Opus/WebM on Android, MP4/AAC on iOS) | Max 20 s per recording |
| Location | `navigator.geolocation.getCurrentPosition`, `enableHighAccuracy: true`, timeout 15 s | HTTPS only |
| Browsers supported | Chrome for Android 100+, Samsung Internet 20+, Safari iOS 15+ | Test on one low-end Android phone |

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
| Location → postcode reply | ≤ 3 s | ≤ 3 s (no GPU used) | 10 s |
| Text → reply | ≤ 5 s | up to 180 s | 180 s |
| Voice (≤ 15 s clip) → reply | ≤ 12 s | up to 180 s | 180 s |

Cold GPU on the web: the page shows a localised progress message ("Starting up, this can take up to
3 minutes the first time") and keeps waiting up to 180 s. After 180 s it shows a localised retry message.

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
    kind: Literal["menu", "language_menu", "postcode", "validation", "answer",
                  "ask_location", "ask_knew_before", "error", "thanks"]
    lang: str
    text: str                           # final localised text, ≤ 600 chars
    postcode: str | None = None         # "LA-11-A12-GN-01"
    segments: list[tuple[str, str]] | None = None   # [("LA", "Lagos State"), ...] labels from templates
    confidence: Literal["high", "medium", "low"] | None = None
    transcript: str | None = None       # shown to user as "We heard: ..."
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

### 3.4 LLM: intent

- Endpoint: `POST {NATLAS_URL}/v1/chat/completions`, model `natlas`, `temperature: 0`, `max_tokens: 80`,
  `repetition_penalty: 1.12`, `response_format: json_schema`.
- Output (always schema-valid):
```json
{"intent":"get_my_postcode","places_mentioned":["Ibeju-Lekki","Lagos"]}
```
- `intent` ∈ `get_my_postcode | validate_postcode | explain_postcode | greeting | other`.
- Post-processing, in order: (1) a postcode is found in the text (see below) → `validate_postcode`;
  (2) intent is `other` but a keyword hit (`postcode|pósíkòdì|kóòdù|koodu|lamba|adirẹsi|address`)
  → `get_my_postcode`; (3) still `other` → menu.
- Postcode search (in `app/services/postcode.py`, `find_postcode(text)`): case-insensitive, **unanchored**,
  segments separated by `-`, spaces or nothing:
  `\b([A-Z]{2})[\s-]?(\d{2})[\s-]?([A-Z0-9]{3})[\s-]?([A-Z]{2})[\s-]?(\d{2})\b`. Matches are normalised
  to upper case with hyphens (`la 11 a12 gn 01` → `LA-11-A12-GN-01`).
- Acceptance: ≥ 4/5 on `evals/natlas_final_test.py intent` at `temperature: 0`, with held-out eval inputs;
  100% schema-valid; warm latency ≤ 3 s.

### 3.5 LLM: reply (only for `explain_postcode` and the wording around a verified result)

- `temperature: 0.1`, `max_tokens: 200`; language stated in system prompt and at the end of the user turn;
  facts under `FACTS (use only these)` in the user turn.
- Expected output: ≤ 80 words, in the requested language, no URLs, no numbers or place names that are not
  in FACTS. If a postcode is in FACTS, the reply contains it character for character.
- Guard: if the reply contains a URL, a postcode not in FACTS, or is > 120 words, discard it and send the
  template answer instead. Log `reply_kind = "template_fallback"`.

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

Errors arrive as `{"error":{"code","message"}}`. Mapping: `auth_required` or `401/403` → config error
(alert, generic user message); `402` → credits error; `level_not_granted` → its own error kind (we only
call level 1, so it signals a config bug); `429` → wait and retry once after 2 s; timeout (5 s) →
"service is slow, try again"; `404` on lookup → not found.

### 3.7 Web endpoints

| Route | Request | Response |
|---|---|---|
| `GET /` | none | `index.html` (< 50 KB) |
| `POST /api/language` | `{"session":"<uuid>","lang":"yo"}` | `Reply` (`ask_knew_before` for a new user, else menu) |
| `POST /api/location` | `{"session","lat","lng","accuracy_m"}` | `Reply` (postcode) |
| `POST /api/voice` | multipart: `session`, `audio` file | `Reply` (any kind) |
| `POST /api/text` | `{"session","text"}` (≤ 500 chars) | `Reply` |
| `POST /api/feedback` | `{"session","helpful":true}` | `Reply` (thanks) |
| `POST /api/feedback` | `{"session","knew_before":true\|false\|null}` (null = skipped) | `Reply` (menu) |

`session` is a random UUID kept in the browser; the server hashes it before use.

### 3.8 Interaction log

One JSONL line per user turn in a Modal Volume at `/logs/interactions-YYYY-MM-DD-<container>.jsonl`
(date in WAT; one file per container so two containers never append to the same file; the Volume is
committed after each row). `app/store.py` `LogRow` enforces the field list and rejects any `user_hash`
that is not a sha256 hex digest:

```json
{"ts":"2026-10-10T14:52:03+01:00","user_hash":"7f3a…","channel":"web","lang":"yo","input":"voice",
 "transcript":"ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi","intent":"get_my_postcode","postcode_found":null,
 "api_status":null,"latency_ms":{"asr":2400,"llm":2100,"api":null,"total":4700},
 "reply_kind":"ask_location","feedback":null,"knew_postcode_before":null}
```

`knew_postcode_before` is asked once per user, right after the language choice and **before any postcode
is shown** (asking after a result would bias it). It is skippable (→ null) and is set only on the row of
the turn that answers it (null elsewhere).

Sessions live in a `modal.Dict` keyed by `user_hash`, stored as plain dicts:
`{lang, consented, knew_before_asked, awaiting: "knew_before"|"feedback"|null, turns}`. No postcode,
coordinates or text are kept in the session.

`scripts/export_log.py` must glob `interactions-*.jsonl` across all days and containers, merge the rows,
sort them by `ts`, and drop duplicates on `(ts, user_hash)`. Output: `docs/validation_log.csv` plus a summary table (counts per language, input,
intent, completion rate, median latency, helpful %, % who did not know their postcode) for the validation PDF.

---

## 4. Acceptance checklist (before real users)

- [ ] Location path returns `LA-11-A12-GN-01` for `6.6018, 3.3515` in all four languages.
- [ ] Voice path: one recorded clip per language returns a non-empty transcript and a sensible `Reply`.
- [ ] Text path: the three demo sentences (postcode check, Yoruba request, Hausa question) route correctly.
- [ ] Invalid code `LA-11-W06-TC-10` returns "not found", never "valid".
- [ ] LLM guard rejects a reply that contains a URL or an unknown postcode (unit test with a fake LLM).
- [ ] Web page under 50 KB, works on a low-end Android phone over mobile data.
- [ ] Cold GPU: the page shows progress and gets a reply (or a retry message) within 180 s.
- [ ] Log rows contain no coordinates, raw session IDs or audio.
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
