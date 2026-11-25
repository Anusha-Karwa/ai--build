# Slice plan (each slice ends with a test run and a decision-log line)

Run from `BuildDay` with the venv on (Windows: `.venv\Scripts\activate`). Use `--only` while building; the held-back ids (7, 13, 19, 22, 26, 28) are run only in slice 7.

| Slice | What gets built | Test run | Done when |
|---|---|---|---|
| 0 | Walking skeleton: `assistant.py` with `answer(question, user)` returning a hard-coded dict with every key (`rows`, `text`, `sql`, `tokens_in`, `tokens_out`, `cached`); `config.json` (model, fallback, today, timeout, row limit) | `python eval_sql.py --impl assistant.py --rpm 600` | `eval_sql.py` runs end to end and scores near zero |
| 1 | Plan call to `gemini-3.8-flash` returns JSON with SQL; code runs it on a `mode=ro` connection with a timeout and a row limit; numbers returned in `rows` | `--only 1,2,3,4,5,6,8,9,10,11,12,14,15,17` | Lookup and aggregate cases pass (at least 12 of these 14) |
| 2 | Scope in code (`guard.py`): users.json lookup, per-user TEMP views `my_sales` / `my_stores`, authorizer (reads only via views, no writes, ATTACH or PRAGMA), single-SELECT check, out-of-scope store literal turns into a refusal | `--only 21,23,24,25` plus a unit test that a raw `SELECT * FROM sales` is blocked | All non-held-back leak and injection cases pass, 4/4 |
| 3 | Glossary and today in the prompt; `assumption` field always filled and shown in `text` | `--only 18,20` and re-run slice 1 ids | Ambiguous cases pass and slice 1 has not dropped |
| 4 | Refuse and clarify: `action` = refuse for missing data (footfall, competitors, S11 before March 2026) and out-of-scope asks | `--only 27` and re-run 21 to 25 | Unanswerable cases pass and no leak case has dropped |
| 5 | Narration call for `kind` = diagnose only; token and cost meter (tokens from the response metadata, Rs from `config.json` prices); jsonl log | `--only 16`, then full non-held-back run | Case 16 passes; tokens per question printed; Rs per question within 0.50 |
| 6 | Scoped cache; backoff on 429 (max 3 tries); cascade lite first, flash on SQL error or guard reject | `python load_test.py --impl assistant.py --n 60 --workers 8`, then full run | Load test shows cache hits, 0 failures, p95 ≤ 10 s; golden score not lower than slice 5. If lite drops the score, log it and keep flash only |
| 7 | Holdout and verdict | `python eval_sql.py --impl assistant.py` (all 28) | ≥ 25/28, ≥ 5/6 held back, 5/5 on ids 21 to 25; the five-line verdict written |

## Verdict (fill in after slice 7)
| Line | Write |
|---|---|
| 1. Ship or not | Ship to a pilot only: the hq analyst and one store manager, after real login replaces the trusted user name. Not to all 20 users yet |
| 2. Score | 28/28 on the golden set, 6/6 held back, 5/5 leak and injection. Guard tests all pass. Load test: 60 requests, 0 failures, p95 5.5 s, 45 cache hits |
| 3. Cost (1x, 10x, 100x) | ~1,700 tokens in and ~250 out per question (measured). Rupees: fill prices in `config.json`; Rs per question = (1,700 × in + 250 × out) / 1M × USD-INR. Bill = that × 6,000 / 60,000 / 600,000 questions a month |
| 4. Weakest point | The scorer checks numbers, not sentences. On held-back case 13 the lite model's assumption read "...2025-05-01 to 2026-10-31..., wait, 6 complete months..." with correct numbers. We'd notice only by reading replies or from a manager's complaint. Also: 28 questions, all written by us |
| 5. Next | Build: 20 real manager questions and a check that the assumption's dates match the SQL's dates (or have code write the date part). Don't build: a chat UI or an agent loop |

## Slice results
| Slice | Result |
|---|---|
| 0 | 2/28 (injection cases pass on empty output) |
| 1 | 14/14, median 3.3 s, flash |
| 2-5 | 8/8 (leak, injection, ambiguous, unanswerable, diagnose); `test_guard.py` all pass |
| 6 | Load test 0 failures, cache hits 34 to 45 with single-flight; cascade 22/22, median 1.8 s |
| 7 | 28/28, held back 6/6, median 1.4 s, p95 5.6 s |
