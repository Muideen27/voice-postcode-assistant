# Validation summary

Source: interaction log, 13 files, 123 lines (1 duplicates and 0 unreadable lines dropped; 68 rows before 2026-10-11T00:00:00+01:00 excluded; 23 developer test rows excluded (scripts/excluded_hashes.txt)). Developer test turns (/logs/dev/) are never included.

| Measure | Value |
|---|---|
| Interactions (logged turns after consent) | 31 |
| Content turns (voice, text, location) | 21 |
| Unique users (salted hashes) | 2 |
| Turns that reached the Postcode API | 14 (0 with a postcode) |
| Feedback yes / no | 0 / 0 |
| Knew their postcode before: yes / no / skipped or not asked | 0 / 1 / 1 |
| Declined consent (anonymous count) | 0 |
| First / last turn | 2026-10-11T04:44:15+01:00 / 2026-10-12T07:46:13+01:00 |

### By language

| Value | Count | Share |
|---|---|---|
| en | 20 | 65% |
| yo | 9 | 29% |
| ha | 2 | 6% |

### By input type

| Value | Count | Share |
|---|---|---|
| location | 16 | 52% |
| choice | 10 | 32% |
| voice | 4 | 13% |
| text | 1 | 3% |

### Intent mix (text and voice turns)

| Value | Count | Share |
|---|---|---|
| get_my_postcode | 2 | 40% |
| validate_postcode | 2 | 40% |
| other | 1 | 20% |

### Reply kinds

| Value | Count | Share |
|---|---|---|
| postcode | 14 | 45% |
| menu | 10 | 32% |
| error | 2 | 6% |
| ask_location | 2 | 6% |
| ask_code | 2 | 6% |
| ask_knew_before | 1 | 3% |

### Latency per stage (ms)

| Stage | Turns | p50 | p95 |
|---|---|---|---|
| asr | 4 | 2679 | 4621 |
| llm | 5 | 4411 | 16410 |
| api | 14 | 160 | 657 |
| total | 31 | 321 | 9124 |

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
| 2026-10-12 | 0 | 18 | 0 | 0 | not_found | no (official data returned nothing) |
