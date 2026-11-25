import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import config
import cost
import guard
import llm
import loader
import score


def run(path):
    apps = loader.load(path)
    if not apps:
        print(f"no applications in {path}")
        return []
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    Path("reports").mkdir(exist_ok=True)
    rows = []
    for app in apps:
        reply = llm.assess(app["id"], llm.build_prompt(app))
        verdicts = score.normalise(reply.get("criteria", {}))
        fit = score.fit_score(verdicts)
        gaps = score.missing(verdicts)
        term = guard.anti_thesis(app)
        rec = score.recommend(fit, len(gaps), term)
        inr = cost.cost_inr(reply.get("tokens_in", 0), reply.get("tokens_out", 0))
        rows.append({"run_at": run_at, "id": app["id"], "name": app["name"], "fit": fit, "rec": rec,
                     "could_not_establish": gaps, "cost_inr": round(inr, 2),
                     "over_ceiling": inr > config.COST_CEILING_INR})
        Path("reports", app["id"] + ".json").write_text(
            json.dumps({**rows[-1], "criteria": verdicts}, indent=1), encoding="utf-8")

    print(f"{'application':14}{'fit':>5}  recommendation")
    for r in sorted(rows, key=lambda r: -r["fit"]):
        print(f"{r['name']:14}{r['fit']:>5}  {r['rec']}")
    avg = sum(r["cost_inr"] for r in rows) / len(rows)
    flag = "  ** OVER CEILING **" if avg > config.COST_CEILING_INR else ""
    print(f"cost per application: Rs {avg:.2f} (ceiling Rs {config.COST_CEILING_INR}){flag}; "
          f"projected quarter ({config.QUARTERLY_VOLUME} apps): Rs {avg * config.QUARTERLY_VOLUME:,.0f}")
    Path("runs").mkdir(exist_ok=True)
    with open("runs/run_log.jsonl", "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", default="data/applications.csv")
    run(ap.parse_args().apps)
