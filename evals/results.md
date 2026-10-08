# N-ATLaS eval results

One entry per prompt change. Raw data for each run is in `evals/runs/`.

## 2026-10-08: first run of prompts.py v1

- **Run:** `evals/runs/20261008T201603Z.json`, 20:16 UTC.
- **Code:** the commit that adds this file ("Add N-ATLaS prompts, client, guard, fact sheets and evals"). The run used that working tree on top of `e92db3b`, so the run file records `dirty: true`.
- **Endpoint:** `deploy/natlas_serve.py`, vLLM 0.30.0, L4, `--enforce-eager`, max context 4096.
- **Cases:** `evals/cases.py`, held out from the few-shot examples (a test enforces this):
  - 40 intent cases, 10 per language, including noisy ASR-style transcripts.
  - 12 explain cases, 3 per language.

### Intent (temperature 0, JSON schema)

| Language | LLM alone | After regex + low-confidence + safety net | LLM errors |
|---|---|---|---|
| en | 10/10 (100%) | 10/10 (100%) | 0 |
| yo | 10/10 (100%) | 10/10 (100%) | 0 |
| ha | 9/10 (90%) | 9/10 (90%) | 0 |
| ig | 8/10 (80%) | 8/10 (80%) | 0 |
| **All** | **37/40 (92.5%)** | **37/40 (92.5%)** | 0 |

**Target ≥ 85% overall after the safety net: met (92.5%).** Every output was valid JSON that matched the schema.

The safety net changed nothing in this run, because the LLM never returned a wrong `other` that a keyword could fix.

Misses:

| Case | Expected | Got | Effect for the user |
|---|---|---|---|
| ha "Ina kwana" | greeting | other | Menu shown, same as a greeting: harmless. |
| ig "daalu nke ukwu" | greeting | other | Menu shown: harmless. |
| ig "gini bu postcode ohuru a" (noisy) | explain_postcode | get_my_postcode | Asked for location instead of explaining. |

### Explain (temperature 0.1, fact sheet in FACTS)

The guard passed 10 of 12 answers (83%) and rejected 2, which then fall back to the template.

| Case | Guard | Notes (judgement by Claude, not a native speaker) |
|---|---|---|
| en: each part | pass | Correct, grounded. |
| en: postcode from street name | pass | Says to share location. It also implies a street name might be enough ("without knowing the specific street name"), which is slightly misleading. |
| en: since when | pass | Correct, grounded. |
| yo: each part | pass | Yoruba, grounded. Uses "agbegbe" for both district and area, and some words lack tone marks. |
| yo: postcode from street name | pass | **Wrong.** "Dájúdájú! … o gbọdọ kọkọ fun mi ni adirẹsi gangan" means "Certainly! … first give me your exact address". This contradicts the fact that we cannot give a postcode from a place name alone. No invented code or place, so the guard did not catch it. |
| yo: since when | pass | Yoruba with the English word "October". Correct date. |
| ha: each part | **rejected** (number_not_in_facts) | Wrote "lamba 5", a number not in the fact sheet. Template shown instead. |
| ha: postcode from street name | pass | Hausa. Says to share location; the wording is vague ("lambar yanki"). |
| ha: since when | **rejected** (place_not_in_facts) | **Invented places:** "Legas, … Gundumar Ikoyi-Obalende, Unguwar Obalende" as the meaning of LA-11-A12-GN-01. Template shown instead. |
| ig: each part | pass | Igbo, grounded. |
| ig: postcode from street name | pass | Igbo. Says to share location. |
| ig: since when | pass | Igbo, but the month word "Oṅtẹ" looks garbled and "A maliteghachiri" means "restarted". The year and the example are correct. |

- **Language correctness (Claude's judgement):** 12/12 answers are in the requested language, with some English words mixed in (yo "October").
- **Content correct (Claude's judgement):** 9/12. Of the 10 answers the guard passed, 8 are grounded and 2 have content problems (yo street-name answer, ig date).
- **Target "no invented postcode or place in any explain answer":**
  - **Raw model: not met.** 1 of 12 answers invented places (ha "since when").
  - **Shown to users: met.** The guard rejected that answer.
  - The guard caught it only because "Legas" is on its place list. "Ikoyi" and "Obalende" are not on the list, so a reply naming only those would have passed.

### Latency

| Measure | Value |
|---|---|
| Cold start (first `GET /v1/models` after deploy, scaled to zero) | **134 s** |
| Intent, warm: p50 / p95 / max | 1.9 s / 2.4 s / 4.3 s |
| Explain, warm: p50 / p95 / max | 6.7 s / 11.1 s / 11.1 s |

- Intent meets the SPEC target (warm p50 ≤ 3 s).
- Explain is over the SPEC's warm "text → reply ≤ 5 s" budget. The answers are 13–71 words, and the time grows with length: 3.3 s for 13–20 words, 10–11 s for 52–71 words. yo/ha/ig words cost more tokens than English ones.

### Follow-ups (not done; they need a decision)

1. **The guard misses false promises.** The yo street-name answer promised something we cannot do. Options:
   - lower the explain temperature to 0;
   - add to the prompt: "never say you can find a postcode from an address or street";
   - for a question about getting a postcode from a name or address, skip the LLM and answer with the `ask_location` template.
2. **The place list is incomplete.** Add more Lagos and other LGA and area names (Ikoyi, Obalende, …), or reject any capitalised word that is not in FACTS or the user's question. The second option may reject valid yo/ha/ig answers.
3. **Explain latency (p95 11 s).** Options:
   - cap `max_tokens` at about 120;
   - ask for at most 50 words;
   - accept it, since the web page shows progress.
4. **ig noisy "gini bu postcode ohuru a"** goes to get_my_postcode. Could add one more Igbo explain few-shot example (not this phrase).
