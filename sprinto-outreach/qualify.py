import config
import llm
import scrape
import extract

PROMPT = """Sprinto sells compliance automation (SOC 2, ISO 27001, GDPR) to SaaS
companies at Series A-C that are preparing for an audit or pressed by enterprise
customers. Score this company's fit and say if more information is needed.
Return JSON: score (integer 0-100), reason, needs_more (bool).

COMPANY: {company}"""

# Pages the qualifier may pull in, in order, when it asks for more information.
EXTRA_PAGES = ["about", "security", "trust", "customers", "pricing"]


def _merge(company, new):
    """Add newly extracted fields without overwriting known values with nulls/empties."""
    merged = dict(company)
    for k, v in (new or {}).items():
        if v in (None, "", []):
            continue
        if isinstance(v, list) and isinstance(merged.get(k), list):
            merged[k] = merged[k] + [x for x in v if x not in merged[k]]
        else:
            merged[k] = v
    return merged


def _normalise(result):
    """Coerce the model reply into the shape the pipeline relies on."""
    try:
        score = float(result.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    if 0 < score < 1:           # model answered on a 0-1 scale (a bare 1 stays 1/100)
        score *= 100
    return {
        **result,
        "score": round(max(0.0, min(score, 100.0))),
        "reason": result.get("reason", ""),
        "needs_more": bool(result.get("needs_more", False)),
    }


def qualify(domain, company):
    result = _normalise(llm.ask("qualify", domain, PROMPT.format(company=company)))
    pages = iter(EXTRA_PAGES)
    rounds, tried = 0, []
    # A round = one extra page actually read and re-scored. MAX_ROUNDS caps rounds;
    # missing pages are skipped without using one up, and we stop when pages run out.
    while result["needs_more"] and rounds < config.MAX_ROUNDS:
        page = next(pages, None)
        if page is None:
            break
        tried.append(page)
        text = scrape.fetch(domain, page)   # retries transient errors itself
        if not text:
            continue
        rounds += 1
        company = _merge(company, extract.extract(domain, text))
        try:
            result = _normalise(llm.ask("qualify_more", domain, PROMPT.format(company=company)))
        except Exception as e:              # llm.ask already retried; keep the last good answer
            result["reason"] = f"{result['reason']} (re-score failed: {e})"
            break
    result["rounds"] = rounds
    result["pages_tried"] = tried
    result["incomplete"] = result["needs_more"]   # still unsure after the extra pages
    result["qualified"] = result["score"] >= config.QUALIFY_THRESHOLD and not result["incomplete"]
    return result
