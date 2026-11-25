# PRD: Store Analytics Assistant (v1)

Numbers marked *(assumption)* are my best guesses. Check them with a real store manager or head office before treating them as facts.

## 1. Problem in one line
"Store managers ask a question in plain English and get a trusted number."

**Format:** a question box over fixed data, not a chatbot. One question in, one number or small table and one sentence out. Each question stands alone.
**What a wrong number costs:** a reorder on bad stock figures, a discount that loses margin, or a store wrongly flagged as slipping. Correctness comes before speed: a refusal or a stated assumption is better than a confident wrong number.

## 2. Users and jobs
| User | When they ask | Job they do today | How they do it today | What it costs them |
|---|---|---|---|---|
| Store manager (e.g. ana: S03, ravi: S07) | At closing time, daily, before planning tomorrow's stock and staff *(assumption)* | Check their own store's sales, margin, returns and best sellers to plan stock, staff and discounts | Ask head office for a report or wait for the weekly Excel report *(assumption)* | Hours to days of waiting, so they decide on stale numbers or guesses |
| Regional manager (e.g. meera: West, S01 to S04) | Weekly, before the regional review *(assumption)* | Compare the stores in their region and find the ones that are slipping | Combine several store reports in Excel by hand *(assumption)* | About half a day a week of copy-paste, with errors from mismatched definitions |
| Head office analyst (hq: all 12 stores) | Monday mornings for leadership packs, plus ad hoc during the week *(assumption)* | Answer ad hoc questions from managers and leadership | Write SQL or pivot tables for each request | Most of their time goes to repeat lookups instead of analysis |

## 3. Success metrics (write the number, not the adjective)
| Metric | Today | Target | How we measure |
|---|---|---|---|
| Answer correctness on the golden set | 0/28 (nothing built yet) | ≥ 25/28 overall and ≥ 5/6 on the holdout. 100% on leak and injection cases (ids 21 to 25) | `python eval_sql.py --impl assistant.py` and `--holdout` |
| Time to answer | Hours to days (analyst queue) *(assumption)* | Median ≤ 5 s, p95 ≤ 10 s | Median and p95 from `eval_sql.py` and `load_test.py` |
| Cost per question (Rs) | Analyst time, roughly Rs 200+ per request *(assumption)* | ≤ Rs 0.50 per question | Tokens in/out from `eval_sql.py` × the chosen model's price per million tokens (model and price recorded in `DECISION_LOG.md`) |
| Questions a manager can self-serve | ~0% (all go through head office) | ≥ 80% of lookup, aggregate, trend, top-n and diagnose questions answered with no human help (≥ 14 of the 17 such golden cases) | Golden set pass rate on those kinds; later, the share of real questions not escalated to an analyst |
| Holding up under a burst | Not tested | 0 failed requests and p95 ≤ 10 s with 60 questions over 8 workers (a closing-time rush) *(assumption)* | `python load_test.py --impl assistant.py --n 60 --workers 8` |

**Holdout rule:** the 6 held-back cases (ids 7, 13, 19, 22, 26, 28) are never read or used while tuning prompts. We run `--holdout` only to check the result, otherwise the ≥ 5/6 target proves nothing.

## 4. Scale target
Users: ~20 (12 store managers, 4 regional managers, ~4 analysts) *(assumption)*  Questions per day: ~200 (about 10 per user) *(assumption)*  Stores: 12  Rows: ~224,000 sales lines (growing ~12,000 a month)  p95 latency: ≤ 10 s  Budget per month (Rs): ≤ 3,000 (200 questions × 30 days × Rs 0.50) *(assumption)*

| Load | Questions per day | Monthly bill at Rs 0.50 per question |
|---|---|---|
| 1x (v1) | 200 | Rs 3,000 |
| 10x | 2,000 | Rs 30,000 |
| 100x | 20,000 | Rs 3,00,000 |

## 5. In scope for v1
- Plain-English questions over `retail.db` (stores, products, sales) with one number or a small table back, plus one sentence explaining it. The numbers go in `rows`, because that is where `eval_sql.py` looks for them.
- Metrics exactly as defined in `glossary.md`: net sales, gross sales, units sold, cost of goods, margin (Rs and %), average order value, return rate.
- Question types: lookups, aggregates, trends over months, comparisons, top-n, and simple "why" diagnosis (break the change down by category and discount).
- Per-user store access from `users.json`, enforced in code. A user never gets rows from stores outside their list.
- Stating the assumption when a question is ambiguous. Defaults: "sales" or "revenue" means net sales, "recently" means last month, "best store" means highest net sales last month.
- Saying clearly when data does not exist (footfall, competitors, S11 before March 2026) instead of inventing a number.
- Treating text inside data (store notes, product names) as data, never as instructions.
- Read-only SELECT queries with a timeout and a row limit.
- Logging of user, question, SQL, tokens and time. **Never logged:** the API key or `.env` contents, and no result rows in shared logs (they may hold another store's figures).

## 6. Not in v1 (and why)
- **Web or chat UI:** core correctness comes first. A Python function plus the CLI scorer is enough to prove it works.
- **Writing or changing data:** read-only removes a whole class of risk.
- **Forecasts and predictions:** we can't yet show they're accurate, and "trusted number" means historical facts only.
- **Charts:** they're nice to have, but the number has to be right first.
- **Data outside `retail.db`** (footfall, inventory, competitors, weather): none of it exists yet.
- **Real login and SSO:** v1 trusts the user name passed in. Real authentication comes before any live rollout.
- **Multi-turn follow-ups ("and the month before?"):** these add state and new failure modes. Each question stands alone in v1.

## 7. Risks (what is the worst wrong answer, and who gets hurt)
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A manager sees another store's data | Medium (leak and injection questions will try) | High: breaks confidentiality and trust in the whole tool | Filter by the user's stores in code (e.g. restricted views or a mandatory `store_id IN (...)` check on the SQL) before running it. Never rely on the prompt alone. Leak and injection cases must score 100% |
| A wrong number is acted on | Medium (wrong date range, gross vs net, returns not subtracted) | High: wrong stock, discount or staffing decisions | Glossary injected into the prompt, a fixed "today" (2026-11-22), the assumption stated in every answer, the SQL shown or logged for audit, and the golden set run on every change |
| The cache serves one user's answer to another | Medium once a cache is added: ana and ravi both ask "what were my net sales last month?" | High: same as a leak, and it bypasses the SQL check | The cache key includes the user's store scope (or user id), not just the question text. Add a test where two users ask the same question |
| Free-tier rate limits | High at 50+ users or a closing-time burst (the scorer already slows itself to 12 requests a minute) | Medium: failed or very slow answers at peak | Cache repeat questions, retry with backoff (capped), move to a paid tier before rollout, and check with `load_test.py` |
| A bad query scans everything or tries to write | Low (model generation error or injection) | Medium: slow database, or data lost if writes were allowed | Open the database read-only, allow a single SELECT only, and enforce a timeout and a row limit in code |
| Cost runs away | Low at 200/day, higher if loops or retries are added | Medium: monthly budget blown | Flash-tier model, a cap on retries and tokens per question, a cache for repeat questions, cost tracked per question from token counts |
| The model is deprecated or the price changes | High: Gemini models are renamed and retired often (our key listed `gemini-2.5-flash` through `gemini-3.8-flash` on 2026-11-25, and the `-latest` aliases returned 404) | Medium: outage or a cost jump | Model name lives in `config.json`, not in code. Primary and fallback models, with their price per million tokens, are named in `DECISION_LOG.md`. Re-run the golden set before switching |

## 8. Build, buy or configure
Options considered: (a) buy a BI tool with natural-language query (e.g. a Power BI or Looker style "ask a question" feature), (b) configure a generic chat-with-your-database tool, (c) build a thin text-to-SQL layer on Gemini with our own access rules and glossary.
Chosen: (c) build.
Because: the data is small and in one SQLite file. Per-store access and the glossary definitions must be enforced exactly. The golden set lets us prove correctness. A thin build costs a few rupees a day, while BI licences for ~20 users cost much more. Revisit (a) if the scope grows to dashboards and many data sources.

## 9. Open questions
- What do managers actually ask most often? Get 20 real questions to extend the golden set.
- What do managers use today, and how long does an answer take? This replaces the *(assumption)* figures in sections 2 and 3.
- Who owns the glossary when a definition changes (e.g. how returns count)?
- What is the real monthly budget, and who pays for it?
- Which Gemini model is primary and which is the fallback, and what is the current price per million tokens? This confirms or changes the Rs 0.50 target.
- Should a regional manager see company-wide totals (no store breakdown) for benchmarking, or only their own stores? The golden set currently says no: leak case 23 fails if another store's figure appears. Changing this policy means changing the golden set first.
- How is a user's identity verified in production, and who maintains `users.json`?
- Is "today" always the last data date, or the real calendar date once data is refreshed daily?
