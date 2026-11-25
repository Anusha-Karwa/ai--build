"""Store analytics assistant.

answer(question, user) -> dict with rows, text, sql, tokens_in, tokens_out, cached (plus model, cost_inr, secs).
Pipeline: scope (code) -> cache (code) -> plan call (model) -> SQL guard and run (code)
          -> text (code; narration model call only for "why" questions) -> log and cache (code).
"""
import json
import os
import re
import threading
import time

import guard
import llm
import prompts

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "config.json")))
LOG = os.path.join(HERE, "logs", "questions.jsonl")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

_cache = {}
_cache_lock = threading.Lock()
_log_lock = threading.Lock()


def _models():
    if CONFIG.get("cascade"):
        return [CONFIG["fallback_model"], CONFIG["model"]]
    return [CONFIG["model"]]


def cache_key(question, stores):
    q = re.sub(r"\s+", " ", question.strip().lower()).rstrip("?.! ")
    return (q, tuple(sorted(stores)), CONFIG["today"], CONFIG["prompt_version"], tuple(_models()))


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _result_text(cols, rows):
    if not rows or all(v is None for r in rows for v in r):
        return "No data found for that question in this database."
    if len(rows) == 1 and len(cols) == 1:
        return f"Answer: {_fmt(rows[0][0])}"
    out = [" | ".join(cols)]
    out += [" | ".join(_fmt(v) for v in r) for r in rows[:20]]
    if len(rows) > 20:
        out.append(f"... {len(rows)} rows in all")
    return "\n".join(out)


def _log(rec):
    with _log_lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _done(out, user, question, t0, key=None):
    out["secs"] = round(time.time() - t0, 2)
    _log({k: out.get(k) for k in ("sql", "tokens_in", "tokens_out", "model", "cost_inr", "secs", "outcome", "cached")}
         | {"user": user, "question": question, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    if key is not None and out.get("outcome") in ("answered", "refused"):
        with _cache_lock:
            _cache[key] = {k: v for k, v in out.items()}
    return out


def _plan_and_run(question, user, role, stores, model, acc):
    """One model: plan, run, one retry on SQL error. Returns (plan, cols, rows) or raises guard.SqlError."""
    error = None
    for attempt in range(CONFIG["sql_retries"] + 1):
        prompt = prompts.plan_prompt(user, role, stores, guard.STORE_DIR, question, error)
        plan, tin, tout = llm.call(model, prompts.PLAN_SYSTEM, prompt, schema=prompts.Plan)
        acc["tokens_in"] += tin
        acc["tokens_out"] += tout
        acc["cost"].append(llm.cost_inr(model, tin, tout))
        if plan is None:
            error = "the reply was not valid JSON for the schema"
            continue
        if plan.action != "query":
            return plan, [], []
        try:
            cols, rows = guard.run(plan.sql, stores)
            return plan, cols, rows
        except guard.SqlError as e:
            error = str(e)
            acc["sql"] = plan.sql
    raise guard.SqlError(error or "no plan")


_inflight = {}


def answer(question: str, user: str) -> dict:
    """Single-flight wrapper: identical concurrent questions (same scope) wait for the first one."""
    try:
        stores = guard.scope(user)
    except guard.ScopeError:
        return _answer(question, user)
    key = cache_key(question, stores)
    with _cache_lock:
        ev = _inflight.get(key)
        leader = ev is None and key not in _cache
        if leader:
            ev = _inflight[key] = threading.Event()
    if leader:
        try:
            return _answer(question, user)
        finally:
            with _cache_lock:
                _inflight.pop(key, None)
            ev.set()
    if ev is not None:
        ev.wait(timeout=60)
    return _answer(question, user)


def _answer(question: str, user: str) -> dict:
    t0 = time.time()
    out = {"rows": [], "text": "", "sql": "", "tokens_in": 0, "tokens_out": 0, "cached": False,
           "model": "", "cost_inr": None, "outcome": ""}
    try:
        stores = guard.scope(user)
    except guard.ScopeError:
        out.update(text="Unknown user: no access.", outcome="refused")
        return _done(out, user, question, t0)
    mine = ", ".join(stores)

    key = cache_key(question, stores)
    with _cache_lock:
        hit = _cache.get(key)
    if hit:
        res = dict(hit, cached=True, tokens_in=0, tokens_out=0, cost_inr=0.0)
        return _done(res, user, question, t0)

    # Code-level scope check before any model call: named stores or regions outside the user's list.
    if guard.out_of_scope(question, stores):
        out.update(text=f"You only have access to {mine}. I can't show figures for other stores or regions.",
                   outcome="refused")
        return _done(out, user, question, t0, key)

    role = guard.USERS[user]["role"]
    acc = {"tokens_in": 0, "tokens_out": 0, "cost": [], "sql": ""}
    plan = cols = rows = None
    last_err = None
    for model in _models():
        try:
            plan, cols, rows = _plan_and_run(question, user, role, stores, model, acc)
            out["model"] = model
            break
        except guard.ScopeError:
            out.update(text=f"You only have access to {mine}. I can't show figures for other stores.",
                       outcome="refused", model=model)
            plan = None
            break
        except guard.SqlError as e:
            last_err = str(e)
        except Exception as e:  # model or network failure: try the next model
            last_err = f"{type(e).__name__}: {str(e)[:120]}"

    out.update(tokens_in=acc["tokens_in"], tokens_out=acc["tokens_out"])
    costs = acc["cost"]
    out["cost_inr"] = None if (not costs or None in costs) else round(sum(costs), 4)

    if out["outcome"] == "refused":
        out["sql"] = acc["sql"]
        return _done(out, user, question, t0, key)
    if plan is None:
        out.update(text="Sorry, I couldn't answer that reliably. An analyst can help.", outcome="error",
                   sql=acc["sql"])
        out["error"] = last_err
        return _done(out, user, question, t0)

    if plan.action in ("refuse", "clarify"):
        msg = plan.message or "That isn't available in this database."
        # Never let model text name stores outside scope.
        msg = re.sub(r"\bS\d\d\b", lambda m: m.group(0) if m.group(0) in stores else "another store", msg)
        out.update(text=msg, outcome="refused")
        return _done(out, user, question, t0, key)

    rows = [tuple(round(v, 2) if isinstance(v, float) else v for v in r) for r in rows]
    text = f"{plan.assumption}\n{_result_text(cols, rows)}"
    if plan.kind == "diagnose" and rows:
        try:
            why, tin, tout = llm.call(out["model"], prompts.NARRATE_SYSTEM,
                                      prompts.narrate_prompt(question, plan.assumption, cols, rows), max_tokens=600)
            out["tokens_in"] += tin
            out["tokens_out"] += tout
            c = llm.cost_inr(out["model"], tin, tout)
            out["cost_inr"] = None if (c is None or out["cost_inr"] is None) else round(out["cost_inr"] + c, 4)
            text = f"{why.strip()}\n{text}"
        except Exception:
            pass  # the numbers still stand without the sentence
    out.update(rows=rows, text=text, sql=plan.sql, outcome="answered", kind=plan.kind)
    return _done(out, user, question, t0, key)


if __name__ == "__main__":
    import sys
    u, q = sys.argv[1], " ".join(sys.argv[2:])
    r = answer(q, u)
    print(r["text"])
    print(f"\n[sql] {r['sql']}\n[model] {r['model']}  tokens {r['tokens_in']} in / {r['tokens_out']} out  "
          f"cost {r['cost_inr'] if r['cost_inr'] is not None else 'n/a (fill prices in config.json)'}  {r['secs']}s")
