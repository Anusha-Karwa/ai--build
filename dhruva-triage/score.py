import config

POINTS = {"match": 1, "partial": 0.5, "no-match": 0, "insufficient-data": 0}
MISSING = {"verdict": "insufficient-data", "citation": None, "why": "model returned no verdict"}


def normalise(verdicts):
    """One entry per thesis criterion. A criterion the model skipped, gave an unknown
    verdict for, or scored without a citation is treated as not established."""
    out = {}
    for c in config.CRITERIA:
        v = dict(verdicts.get(c) or MISSING)
        if v.get("verdict") not in POINTS:
            v = {**MISSING, "why": f"unknown verdict {v.get('verdict')!r}"}
        elif v["verdict"] != "insufficient-data" and not v.get("citation"):
            v = {**MISSING, "why": f"verdict {v['verdict']!r} given without a citation"}
        out[c] = v
    return out


def raw_score(verdicts):
    """Sum of points across the six criteria, 0 to 6. Unestablished criteria score 0."""
    return sum(POINTS.get(v["verdict"], 0) for v in verdicts.values())


def fit_score(verdicts):
    """Absolute fit out of 10, independent of the other applications in the batch."""
    return round(raw_score(verdicts) / len(config.CRITERIA) * 10, 1)


def missing(verdicts):
    return [c for c, v in verdicts.items() if v["verdict"] == "insufficient-data"]


def recommend(fit, n_missing, term):
    if term:
        return f"PASS (anti-thesis: {term})"
    if n_missing > config.MIN_EVIDENCE:
        return "INSUFFICIENT DATA TO RECOMMEND"
    return "ADVANCE TO CALL" if fit >= config.ADVANCE_AT else "PASS"
