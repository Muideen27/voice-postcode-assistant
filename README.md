# Voice Postcode Assistant

**Live: <https://muideen27--voice-postcode-web.modal.run>**

Get, check and understand your new Nigerian postcode **by speaking Yorùbá, Hausa, Igbo or Nigerian
English**. Built for the National AI Innovation Challenge (NAIC) 2026, Innovation & Enterprise track,
PS2 Voice-First Access, as a low-bandwidth mobile web app.

- Speech is recognised by the official **NCAIR1** speech models for the language you choose.
- **N-ATLaS** understands what you asked for (your postcode, checking a code, or a question).
- Postcodes come **only** from the official Nigeria Postcode API; the AI never invents a postcode or a place.
- No name, phone number or NIN is asked for. Your location is used once and not kept; voice notes are
  deleted after they are read.

N-ATLaS is an initiative of the Federal Ministry of Communications, Innovation and Digital Economy, and
powered by Awarri Technologies.

## Try it in 3 steps

1. Open the link on a phone and pick your language.
2. Agree to the short privacy notice, then tap **Tap and speak** and ask, in your language, "What is my
   postcode?" or "What does each part of a postcode mean?". Or say or type a postcode to check it, such as
   `LA 11 A12 GN 01`.
3. Tap **Get my postcode** and allow location to look up the postcode where you stand.

The **Pilot dashboard** tab shows the real, anonymised pilot numbers (it is empty before the pilot starts).

## Note for judges: first request after a quiet period

The speech and language models run on GPUs that switch off when nobody is using them, to keep costs low.
The page loads in about a second, and it starts the models as soon as it opens. If they were off, the
**first** spoken or typed request can wait about two minutes; the page says "Waking up the language
model, about 2 minutes, the first time only". After that, replies take a few seconds. Location and postcode
checks never wait for the language model.

Note: on 9–12 Oct 2026 the official Postcode API returned no postcode data at all, even for codes that were
valid on 3 Oct (details in the validation report). Until the data returns, location and code checks answer
honestly that the official database has no postcode yet.

## Documents

| Document | |
|---|---|
| N-ATLaS integration | [`docs/submission/02_natlas_integration.pdf`](docs/submission/02_natlas_integration.pdf) |
| Validation report | [`docs/submission/03_validation.pdf`](docs/submission/03_validation.pdf) |
| Technical documentation | [`docs/submission/04_technical_docs.pdf`](docs/submission/04_technical_docs.pdf) |
| Video plan | [`docs/submission/05_video_plan.md`](docs/submission/05_video_plan.md) |
| Team profile | [`docs/submission/06_team_profile.md`](docs/submission/06_team_profile.md) |
| Design vs build screenshots | [`docs/ui-compare/README.md`](docs/ui-compare/README.md) |
| Engineering guide / contracts | [`CLAUDE.md`](CLAUDE.md), [`SPEC.md`](SPEC.md) |
| Pilot checklist | [`docs/pilot_checklist.md`](docs/pilot_checklist.md) |
