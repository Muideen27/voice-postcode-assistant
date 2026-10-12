---
title: "Validation report — Voice Postcode Assistant"
---

# Validation report

**Voice Postcode Assistant** · NAIC 2026 · PS2 Voice-First Access · civic information ·
Live: <https://muideen27--voice-postcode-web.modal.run>

N-ATLaS is an initiative of the Federal Ministry of Communications, Innovation and Digital Economy, and
powered by Awarri Technologies.

All numbers in this report come from the service's own anonymised interaction log, exported with
`scripts/export_log.py --pull --since {{PILOT_START}}` and filled in by `scripts/fill_submission.py`.
Developer test turns are never counted (they are logged to a separate folder, and the export starts at
the pilot start time).

## 1. Method

- **Pilot dates:** {{PILOT_DATES}} (first logged turn {{PILOT_FIRST_TURN}}, last {{PILOT_LAST_TURN}}).
- **Testers:** {{N_TESTERS}}, all non-developers. Recruitment: {{TESTER_RECRUITMENT}}
- **Shared phone:** one session on 12 Oct (08:07–08:53 WAT, 36 logged turns in all four languages) was
  one phone used by several different people, so the session count (7) is lower than the number of people.
- **Fellow participants:** some testers on 12 Oct were fellow NAIC participants; they could not be
  separated in the anonymised log.
- **Developer sessions excluded:** the developer's own test sessions and device are left out of every
  number (salted session hashes listed in `scripts/excluded_hashes.txt`).
- **Setting:** testers used their own Android phones and mobile data, opening the live link. A facilitator
  read the tester script (`docs/pilot_checklist.md`, section 4) and did not touch the phone. During
  sessions both GPUs were kept warm with `scripts/warm.sh`.
- **What a tester did:** pick a language → read the welcome and consent → answer "Did you know your new
  postcode before today?" (yes / no / skip) → get a postcode by sharing location, ask by voice, check a
  code, ask a question → answer "Did this help?" after each reply.
- **Consent:** shown in the chosen language before anything is stored. Declining deletes the session; only
  an anonymous daily count of declines is kept.
- **Privacy:** no names, phone numbers or NIN are asked for. Location is used for one lookup and never
  stored. Users appear only as salted one-way hashes. Voice recordings are deleted after transcription.
  Stored text is scrubbed of numbers, phones and emails and capped at 300 characters. No coordinates,
  audio or raw session IDs are in the log.

## 2. Headline numbers

| Measure | Value |
|---|---|
| Real interactions (logged turns after consent; PS2 minimum 50) | **{{N_INTERACTIONS}}** |
| Content turns (voice, text, location) | {{N_CONTENT_TURNS}} |
| Unique users (browser sessions; a phone shared by several people counts once) | {{N_USERS}} |
| Turns that reached the Postcode API / with a postcode | {{N_POSTCODE_TURNS}} / {{N_WITH_POSTCODE}} |
| "Did this help?" yes / no | {{FEEDBACK_YES}} / {{FEEDBACK_NO}} |
| Knew their postcode before: yes / no / skipped or not asked | {{KNEW_YES}} / {{KNEW_NO}} / {{KNEW_SKIPPED}} |
| Declined consent (anonymous count) | {{N_DECLINES}} |

### Interactions by language

{{CHART_LANGUAGE}}

{{TABLE_LANGUAGE}}

### Input type

{{CHART_INPUT}}

{{TABLE_INPUT}}

### What people asked for (voice and text turns)

{{CHART_INTENT}}

{{TABLE_INTENT}}

## 3. Findings

**Did people know their postcode before?** Asked once, right after consent and **before any postcode is
shown**, so the answer is not biased by the result: {{KNEW_NO}} said no, {{KNEW_YES}} said yes, and
{{KNEW_SKIPPED}} skipped or were not asked.

**Feedback.** After each answer the app asks "Did this help?": {{FEEDBACK_YES}} yes and {{FEEDBACK_NO}} no.

**Latency per stage** (milliseconds; voice = speech recognition, llm = intent, api = Postcode API):

{{TABLE_LATENCY}}

**Declines per day:**

{{TABLE_DECLINES}}

### Example transcripts

At most three real transcripts, each checked by hand to contain no personal data (no names, phone
numbers, addresses or other identifying details). All other evidence in this report is aggregated.

{{EXAMPLE_TRANSCRIPTS}}

## 4. Official postcode data during the pilot

The service checks one known postcode (`LA-11-A12-GN-01`, valid on 3 Oct 2026) at every web start and
every 30 minutes, and records the result per day:

{{TABLE_CANARY}}

## 5. Limitations (stated plainly)

1. **The official test data has been empty since at least 9 Oct 2026.** Evidence:
   - 3 Oct 2026: a live reverse lookup of 6.6018, 3.3515 (Ikeja) returned `LA-11-A12-GN-01`, and a lookup of
     that code returned `valid` (recorded responses in `tests/fixtures/postcode/`).
   - 9 Oct 2026: with a valid key, reverse lookups at nine places (Ikeja ×2, Victoria Island, Yaba, Abuja
     Wuse 2, Abuja Garki, Kano, Enugu, Ibadan) all returned "no postcode within range", the same code
     returned `not_found`, and the API's own autocomplete for "LA11" returned no suggestions.
   - From 10 Oct 2026 the canary above records the daily result (`not_found` = valid key, no data).
     NIPOST has been informed.
   During these days the app never invents a postcode. A location lookup answers honestly: "The official
   postcode database has no postcode for this spot yet". For a **code check** (typed or spoken) the app
   uses the canary: when the lookup says `not_found` and today's canary is not `valid`, it does not tell the
   user the code is wrong. It replies "{code} has the right format, but the official postcode database
   can't confirm it today. Here is what each part means:" followed by the meaning of each part (state,
   Local Government Area, district, area, unit), and logs `api_status = unconfirmed_db_down` with
   `postcode_found` left empty. When the canary is `valid`, a `not_found` code is reported as not found.
   In the numbers above, unconfirmed code checks are therefore neither "valid" nor "not found".
2. **Igbo speech recognition is labelled beta** in the app; Igbo users are offered "Type instead".
3. **Languages not yet reviewed by native speakers:** {{UNREVIEWED_LANGUAGES}}.
4. **Speech recognition accuracy was measured offline only** (recorded test clips), not live: the pilot
   does not store audio, so live word accuracy cannot be computed.
5. Location answers depend on the phone's GPS accuracy and on the API's 50 m / 250 m search radius.
   **Repeated attempts are counted as logged:** on 12 Oct one user shared their location four times within
   20 seconds (11:28–11:29 WAT); each attempt is a separate logged turn and is included in the totals,
   as is every other turn. Interactions are counted exactly as logged, without merging repeats.
6. Language-model cold start (about 2 minutes) is avoided during sessions by keeping the GPUs warm; outside
   sessions the first request may wait and the page says so.
