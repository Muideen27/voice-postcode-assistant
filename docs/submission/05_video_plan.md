# Video plan (3–5 minutes)

**Voice Postcode Assistant** · NAIC 2026 · PS2 Voice-First Access. Record on a real Android phone (screen
recording + a second camera on the speaker), with both GPUs warm (`scripts/warm.sh 60`). Everything shown
must be real; on-screen captions in English; the speaker talks in Yorùbá or Hausa with English subtitles.

> **Open before recording (not built; decide or drop):** the brief mentions demo-mode segments with a
> "Recorded data" chip and a "finder handoff" after a not-found location. Neither exists in the app today
> (feature freeze 9 Oct). Until they are built and approved, every segment below is shot **live**, and no
> segment pretends to be live when it is not.

| # | Time | Shot | What is on screen | Voice-over / caption |
|---|---|---|---|---|
| 1 | 0:00–0:25 | Problem | A street in Nigeria; a person asked for their postcode on a form, unsure | "Nigeria's new postcodes went live on 1 October 2026. Most people don't know theirs, and many don't type." |
| 2 | 0:25–0:40 | Open the link | Phone opens the link; language screen in the phone's language; Igbo marked beta; N-ATLaS attribution visible | "Pick your language: Yorùbá, Hausa, Igbo or English." |
| 3 | 0:40–0:55 | Consent | Welcome + consent in Yorùbá; tap "I agree"; the "Did you know your postcode before today?" question | "Nothing is stored before you agree. No name, phone number or NIN." |
| 4 | 0:55–1:40 | **Real user speaking** | A non-developer tester taps "Tap and speak" and asks in Yorùbá or Hausa for their postcode; "We heard: …" shows the transcript; the app asks for location | "Speech is recognised by the official NCAIR1 Yorùbá model. N-ATLaS understands the request." |
| 5 | 1:40–2:10 | Location path (honest) | "Get my postcode" → "Finding your building…" → the real reply. If the official database still has no data: "The official postcode database has no postcode for this spot yet." | "Postcodes come only from the official Nigeria Postcode API. If it has no data, we say so — the model never invents one." |
| 6 | 2:10–2:40 | Code explanation | Say or type "LA 11 A12 GN 01": the reply and the segment explanation (state, LGA, district, area, unit) | "A code check goes straight to the Postcode API, without the language model." |
| 7 | 2:40–3:05 | FAQ | Ask "What does each part of a postcode mean?" in Hausa; the reviewed answer appears | "Answers to common questions are reviewed templates chosen by N-ATLaS, not free text." |
| 8 | 3:05–3:25 | Privacy | The FAQ privacy answer; a glimpse of the dashboard's "No transcripts, names, phone numbers or locations are shown" | "Location is used once. Voice notes are deleted after transcription. Users are one-way hashes." |
| 9 | 3:25–3:55 | **Dashboard with real numbers** | "Pilot dashboard" tab after the pilot: interactions vs the PS2 minimum of 50, valid-postcode rate, "did not know before", "said it helped", today's database status | "These are the real pilot numbers, counted from the pilot start." |
| 10 | 3:55–4:30 | Architecture slide | The diagram from the technical documentation | "Four NCAIR1 speech models and N-ATLaS on Modal L4 GPUs; facts from the Postcode API; everything in four languages." |
| 11 | 4:30–4:45 | Close | The live link and the attribution | "N-ATLaS is an initiative of the Federal Ministry of Communications, Innovation and Digital Economy, and powered by Awarri Technologies." |

Checklist before recording: tester consent to be filmed (separate from app consent), GPUs warm, phone in
Do Not Disturb, dashboard opened after `PILOT_START` is set, no notifications or personal data on screen.
