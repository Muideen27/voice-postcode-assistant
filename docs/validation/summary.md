# Validation summary

Source: interaction log, 13 files, 192 lines (1 duplicates and 0 unreadable lines dropped; 68 rows before 2026-10-11T00:00:00+01:00 excluded; 44 developer test rows excluded (scripts/excluded_hashes.txt)). Developer test turns (/logs/dev/) are never included.

| Measure | Value |
|---|---|
| Interactions (logged turns after consent) | 79 |
| Content turns (voice, text, location) | 45 |
| Unique users (salted hashes) | 7 |
| Turns that reached the Postcode API | 22 (0 with a postcode) |
| Feedback yes / no | 6 / 1 |
| Knew their postcode before: yes / no / skipped or not asked | 1 / 4 / 2 |
| Declined consent (anonymous count) | 0 |
| First / last turn | 2026-10-11T05:57:07+01:00 / 2026-10-12T11:37:46+01:00 |

### By language

| Value | Count | Share |
|---|---|---|
| en | 28 | 35% |
| yo | 22 | 28% |
| ha | 15 | 19% |
| ig | 14 | 18% |

### By input type

| Value | Count | Share |
|---|---|---|
| choice | 34 | 43% |
| location | 25 | 32% |
| voice | 17 | 22% |
| text | 3 | 4% |

### Intent mix (text and voice turns)

| Value | Count | Share |
|---|---|---|
| get_my_postcode | 10 | 50% |
| validate_postcode | 8 | 40% |
| other | 2 | 10% |

### Reply kinds

| Value | Count | Share |
|---|---|---|
| postcode | 22 | 28% |
| menu | 21 | 27% |
| ask_location | 10 | 13% |
| ask_code | 9 | 11% |
| ask_knew_before | 7 | 9% |
| thanks | 7 | 9% |
| error | 3 | 4% |

### Latency per stage (ms)

| Stage | Turns | p50 | p95 |
|---|---|---|---|
| asr | 17 | 1751 | 20634 |
| llm | 20 | 2676 | 4565 |
| api | 22 | 124 | 320 |
| total | 79 | 309 | 7832 |

### Declines per day

| Date (WAT) | Declines |
|---|---|
| — | 0 |

### Postcode API data canary per day

Lookup of LA-11-A12-GN-01 (level 1) at each web container start and every 30 minutes.

| Date (WAT) | valid | not_found | auth | error | Last result | Official data available? |
|---|---|---|---|---|---|---|
| 2026-10-09 | 0 | 0 | 29 | 0 | auth | unknown |
| 2026-10-10 | 0 | 20 | 35 | 0 | not_found | no (official data returned nothing) |
| 2026-10-11 | 0 | 55 | 0 | 0 | not_found | no (official data returned nothing) |
| 2026-10-12 | 0 | 26 | 0 | 0 | not_found | no (official data returned nothing) |
