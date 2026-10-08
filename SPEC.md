# SPEC.md: stack, versions, constraints and expected outputs

Companion to CLAUDE.md. CLAUDE.md says how we work; this file says exactly what we build with and
what each part must return. Any change to a version, contract or budget here needs a matching code
change and a note in the changelog at the bottom.

Status markers: **[verified]** = seen working in our own tests or logs, **[pin]** = must be confirmed
and written in before the first app deploy, **[target]** = budget we design for, measured in the pilot.

---

## 1. Stack and versions

### Runtime platform

| Component | Version | Status | Notes |
|---|---|---|---|
| Modal (hosting, GPUs, secrets, storage) | client: run `modal --version` | [pin] | Workspace `muideen27`, Starter plan, spend cap $30 |
| Modal image base | `debian_slim`, Python **3.11** | [verified] | All server code targets 3.11 |
| Laptop dev env | Ubuntu 24.04, Python **3.12** venv | [verified] | Code must run on both 3.11 and 3.12 |
| GPU for LLM | NVIDIA **L4** (24 GB) | [verified] | N-ATLaS BF16 uses ~15 GiB; 4.4 GiB left for KV cache |
| GPU for ASR | NVIDIA **L4**, same class | [target] | Separate container; merge with LLM only if memory allows |
| ffmpeg | Debian package in image; 6.1.1 on laptop | [verified laptop] | Converts OGG/Opus, WebM, MP4/AAC to 16 kHz mono WAV |

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
| vllm | read from `serve.log` startup line or `pip show vllm` in the image | [pin] | LLM serving (verified working build, unpinned so far) |
| torch | 2.14.1 | [verified] | ASR inference |
| transformers | 5.18.0 | [verified] | Whisper ASR (`WhisperForConditionalGeneration`) |
| huggingface_hub | 1.33.0 | [verified] | Model download, revision pinning |
| accelerate | 1.15.0 | [verified] | Model loading |
| fastapi | 0.142.4 | [verified] | HTTP app (web + Twilio) |
| uvicorn | 0.54.0 | [verified] | Pulled in by `fastapi[standard]` |
| pydantic | 2.13.5 | [verified] | Payload models |
| httpx | 0.28.1 | [verified] | Outbound calls (Postcode API, LLM) |
| twilio | 9.11.2 | [verified] | Signature validation, TwiML |
| python-multipart | 0.0.32 | [verified] | Form posts (Twilio, audio upload) |
| librosa | laptop version | [pin] | Audio loading for ASR |
| soundfile | laptop version | [pin] | Audio I/O |
| pytest | latest available at pin time | [pin] | Tests, dev only |
| ruff | latest available at pin time | [pin] | Lint and format, dev only |

### External services

| Service | Endpoint | Auth | Status | Limits we design for |
|---|---|---|---|---|
| Postcode API (NIPOST gateway) | `https://api.postcode.gov.ng` | `X-API-Key` (test key) | [verified] | Lookup **L1 only**; 600 req/window; 5 s timeout |
| Twilio WhatsApp sandbox | webhook `POST /twilio` | `X-Twilio-Signature` | [verified text only] | Reply inline via TwiML within ~15 s; trial blocks outbound API, voice and location not yet received |
| Hugging Face Hub | model downloads at build time only | `HF_TOKEN` secret | [verified] | Never called per request |

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
4. Privacy: no NIN, names, phone numbers, coordinates or audio stored. IDs = `sha256(salt + channel_user_id)`.
5. Licence: attribution shown in welcome and footer; < 1,000 active users per 30 days.
6. Budget: Modal spend ≤ $30 for October. GPUs warm only during scheduled sessions.
7. Every outbound call has a timeout and a localised fallback message.

### Latency budgets [target]

| Path | Warm | Cold (GPU asleep) | Hard limit |
|---|---|---|---|
| Location → postcode reply | ≤ 3 s | ≤ 3 s (no GPU used) | 10 s |
| Text → reply | ≤ 5 s | up to 3 min | WhatsApp 15 s; web shows progress |
| Voice (≤ 15 s clip) → reply | ≤ 12 s | up to 3 min | WhatsApp 15 s; web shows progress |

On WhatsApp, if the GPU is cold, reply immediately with the localised "still waking up, send it again in a
minute" message rather than timing out.

---

## 3. Component contracts and expected outputs

### 3.1 `Event` (every channel produces this)

```python
@dataclass
class Event:
    user_hash: str                      # sha256(salt + channel id)
    channel: Literal["whatsapp", "web"]
    type: Literal["text", "voice", "location", "choice", "feedback"]
    lang: Literal["en", "yo", "ha", "ig"] | None
    text: str | None = None             # typed text or menu digit
    audio: bytes | None = None          # raw upload, any of ogg/webm/mp4
    audio_mime: str | None = None
    lat: float | None = None            # never persisted
    lng: float | None = None
```

### 3.2 `Reply` (the orchestrator returns this; channels render it)

```python
@dataclass
class Reply:
    kind: Literal["menu", "language_menu", "postcode", "validation", "answer",
                  "ask_location", "error", "thanks"]
    lang: str
    text: str                           # final localised text, ≤ 600 chars for WhatsApp
    postcode: str | None = None         # "LA-11-A12-GN-01"
    segments: list[tuple[str, str]] | None = None   # [("LA", "State · Lagos"), ...]
    confidence: Literal["high", "medium", "low"] | None = None
    transcript: str | None = None       # shown to user as "We heard: ..."
```

Example expected output for a location in Ikeja (en):

```json
{"kind":"postcode","lang":"en","postcode":"LA-11-A12-GN-01","confidence":"high",
 "segments":[["LA","State · Lagos"],["11","Local Government Area"],["A12","District"],["GN","Area"],["01","Your building"]],
 "text":"Your postcode is LA 11 A12 GN 01.\nLA = Lagos State\n11 = your Local Government Area\nA12 = your district\nGN = your area\n01 = your building\nDid this help? Reply 1 for yes, 2 for no."}
```

### 3.3 ASR service

- Call: `ASR.transcribe(lang, audio: bytes, mime: str) -> AsrResult`
- Input: ≤ 20 s and ≤ 2 MB of audio, any of OGG/Opus, WebM/Opus, MP4/AAC, WAV. Rejected otherwise.
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
- Post-processing, in order: (1) postcode regex `^[A-Z]{2}-?\d{2}-?[A-Z0-9]{3}-?[A-Z]{2}-?\d{2}$` found in
  the text → `validate_postcode`; (2) intent is `other` but a keyword hit (`postcode|pósíkòdì|kóòdù|koodu|lamba|adirẹsi|address`)
  → `get_my_postcode`; (3) still `other` → menu.
- Acceptance: ≥ 4/5 on `tests/natlas_final_test.py intent`; 100% schema-valid; warm latency ≤ 3 s.

### 3.5 LLM: reply (only for `explain_postcode` and the wording around a verified result)

- `temperature: 0.1`, `max_tokens: 200`; language stated in system prompt and at the end of the user turn;
  facts under `FACTS (use only these)` in the user turn.
- Expected output: ≤ 80 words, in the requested language, no URLs, no numbers or place names that are not
  in FACTS. If a postcode is in FACTS, the reply contains it character for character.
- Guard: if the reply contains a URL, a postcode not in FACTS, or is > 120 words, discard it and send the
  template answer instead. Log `reply_kind = "template_fallback"`.

### 3.6 Postcode client

| Function | Call | Expected output |
|---|---|---|
| `reverse(lat, lng)` | `GET /v1/search/reverse?lat&lng&max_distance_m=50` | `{"found":true,"postcode":"LA-11-A12-GN-01","display":"LA 11 A12 GN 01","confidence":"high","distance_m":9.2}` or `{"found":false}` |
| `lookup(code)` | `GET /v1/lookup?code=&level=1` | `{"postcode":"LA-11-A12-GN-01","valid":true,"status":"valid"}` or `valid:false, status:"not_found"` |
| `segments(code)` | local split + `data/states.json` | `[("LA","Lagos"),("11",None),("A12",None),("GN",None),("01",None)]` |

Error mapping: `401/403` → config error (alert, generic user message); `402` → credits error; `429` → wait
and retry once after 2 s; timeout (5 s) → "service is slow, try again"; `level_not_granted` → continue at L1.

### 3.7 Web endpoints

| Route | Request | Response |
|---|---|---|
| `GET /` | none | `index.html` (< 50 KB) |
| `POST /api/language` | `{"session":"<uuid>","lang":"yo"}` | `Reply` (menu) |
| `POST /api/location` | `{"session","lat","lng","accuracy_m"}` | `Reply` (postcode) |
| `POST /api/voice` | multipart: `session`, `audio` file | `Reply` (any kind) |
| `POST /api/text` | `{"session","text"}` (≤ 500 chars) | `Reply` |
| `POST /api/feedback` | `{"session","helpful":true}` | `Reply` (thanks) |

`session` is a random UUID kept in the browser; the server hashes it before use.

### 3.8 Twilio channel

- `POST /twilio` (form-encoded). Validate `X-Twilio-Signature` against the public https URL.
- Map: `Body` → text, `NumMedia>0 & MediaContentType0 audio/*` → voice (download `MediaUrl0` with basic auth),
  `Latitude/Longitude` → location, digits `1-4` before a language is set → language choice.
- Respond with TwiML `<Response><Message>…</Message></Response>` within 15 s. Deduplicate by `MessageSid`.

### 3.9 Interaction log

One JSONL line per user turn in a Modal Volume at `/logs/interactions-YYYY-MM-DD.jsonl`:

```json
{"ts":"2026-10-10T14:52:03+01:00","user_hash":"7f3a…","channel":"web","lang":"yo","input":"voice",
 "transcript":"ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi","intent":"get_my_postcode","postcode_found":null,
 "api_status":null,"latency_ms":{"asr":2400,"llm":2100,"api":null,"total":4700},
 "reply_kind":"ask_location","feedback":null,"knew_postcode_before":false}
```

`scripts/export_log.py` → `docs/validation_log.csv` plus a summary table (counts per language, input,
intent, completion rate, median latency, helpful %) for the validation PDF.

---

## 4. Acceptance checklist (before real users)

- [ ] Location path returns `LA-11-A12-GN-01` for `6.6018, 3.3515` in all four languages.
- [ ] Voice path: one recorded clip per language returns a non-empty transcript and a sensible `Reply`.
- [ ] Text path: the three demo sentences (postcode check, Yoruba request, Hausa question) route correctly.
- [ ] Invalid code `LA-11-W06-TC-10` returns "not found", never "valid".
- [ ] LLM guard rejects a reply that contains a URL or an unknown postcode (unit test with a fake LLM).
- [ ] Web page under 50 KB, works on a low-end Android phone over mobile data.
- [ ] Log rows contain no coordinates, phone numbers or audio.
- [ ] Attribution visible on welcome screen and footer.
- [ ] Every template string reviewed by a native speaker (no `TODO_REVIEW` left in yo/ha/ig).

---

## Changelog

- 2026-10-08: first version.
