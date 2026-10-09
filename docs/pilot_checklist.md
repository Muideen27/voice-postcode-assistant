# Pilot checklist

Live page: **https://muideen27--voice-postcode-web.modal.run** (Modal app `voice-postcode`).
Run every step in order before the first real user. Tick each box and write the date and who did it.

## 1. Before the pilot day

- [ ] **Postcode API key in the app secret.** The `voice-postcode` secret must hold the real key. On 9 Oct
      it still held the 15-character placeholder (`invalid_api_key`). Re-create it (a new salt is fine
      until pilot data exists):
      ```bash
      modal secret create voice-postcode --force POSTCODE_API_KEY=<real key> HASH_SALT=$(openssl rand -hex 32)
      modal deploy app/main.py
      ```
      Check: the next canary line is not `"auth"` (`modal app logs voice-postcode | grep canary`).
- [ ] **Official data is back.** The canary reports `"canary": "valid"` (LA-11-A12-GN-01 found).
      If it still says `not_found`, decide: run the pilot without location/validation results (users see
      "The official postcode database has no postcode for this spot yet"), or wait. The canary table
      in `docs/validation/summary.md` records which days had no data.
- [ ] **Native-speaker reviews applied.** For yo, ha and ig, the three sheets
      `docs/review/<lang>.csv`, `faq_<lang>.csv` and `ui_<lang>.csv` are filled and applied:
      ```bash
      python scripts/apply_review.py yo                          # then ha, ig
      python scripts/apply_review.py yo docs/review/faq_yo.csv
      python scripts/apply_review.py yo docs/review/ui_yo.csv
      ```
- [ ] **Gates pass:** `pytest -q` and `pytest -m pilot` (fails until every `_todo_review` list is empty),
      `ruff check .`. Then `modal deploy app/main.py` so the reviewed strings go live.

## 2. On the pilot day, 30 minutes before testers arrive

- [ ] `scripts/warm.sh 120` (or the session length). It prints the LLM and ASR cold-start times and resets
      both GPUs to 0 when the window ends or on Ctrl+C. Leave the terminal open.
- [ ] Note the **pilot start time** (WAT, ISO format, e.g. `2026-10-10T09:00:00+01:00`); export uses it
      to leave out the developer smoke tests.

## 3. Real-phone check (Android, Chrome), before testers

On a low-end Android phone with mobile data:

- [ ] Page opens over mobile data; first screen shows "Choose your language" in the phone's language
      (en/yo/ha/ig) and the N-ATLaS attribution.
- [ ] **Microphone:** Chrome asks for permission; recording shows "Listening…", Stop works, the 20 s
      limit stops automatically, the reply shows "We heard: …". Deny the permission once: the
      microphone message appears with "Type instead".
- [ ] **Location:** Chrome asks for permission; "Finding your building…", then a result or the
      no-data message. Deny once: the location message appears.
- [ ] **Copy postcode** puts the code on the clipboard (only when a postcode is shown).
- [ ] **Dark mode:** switch the phone to dark mode; text and buttons stay readable (prototype dark tokens).
- [ ] Yorùbá, Hausa and Igbo letters (ẹ ọ ṣ ɓ ɗ ƙ ƴ ị ụ ṅ) display correctly, with no boxes.
- [ ] Feedback Yes/No shows the thank-you line.

## 4. Script for testers (read aloud; testers are not developers)

> Thank you for helping. This is a free helper for Nigeria's new postcodes. It does not ask for your name,
> phone number or NIN, and it does not keep your location or your voice.
>
> 1. Open the link and pick your language.
> 2. Read the welcome and tap **I agree** if you are happy to continue (or **No, thanks** to stop).
> 3. Answer the question about whether you knew your postcode (or tap **Skip**).
> 4. Tap **Get my postcode** and allow location. Stand outside, near your building, if you can.
> 5. Tap **Tap and speak** and ask, in your language, something like "What is my postcode?" or
>    "What does each part of a postcode mean?". Tap **Stop** when you finish.
> 6. If you have a postcode, say it or type it to check it.
> 7. After each answer, tap **Yes** or **No** for "Did this help?".
>
> Please use your own words. There are no wrong answers; we are testing the helper, not you.

The facilitator writes down only problems seen (not names or numbers) in `docs/validation/notes.md`.

## 5. After each session

- [ ] `scripts/warm.sh off` if the window is still open and the session is over.
- [ ] `python scripts/export_log.py --pull --since <pilot start>` → `docs/validation/interactions.csv`
      and `summary.md` (interactions, unique users, languages, inputs, intents, feedback, knew-before,
      latency per stage, declines, canary days). Target: 50+ interactions from non-developer users.
- [ ] Check `summary.md` for any day with canary `not_found` or `auth` and add a sentence about it to
      the validation report.
