"""Tests for the qualify step: threshold, agent-loop rounds, and retries.

Run from the project folder:   .venv\\Scripts\\python -m unittest -v
No network or paid API calls: everything runs on fixtures/ or stubbed replies.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
config.OFFLINE = True
import extract, llm, qualify, requests, run, scrape  # noqa: E402

# What each test company should come out as, given fixtures/llm_responses.json.
EXPECTED = {
    "finlytic.example":  (86, True),    # Series B SaaS, SOC 2 pressure
    "cartwheel.example": (78, True),    # Series A SaaS, ISO 27001 blocking deals
    "zenstack.example":  (74, True),    # Series C SaaS, GDPR + SOC 2 buyers
    "orbitdocs.example": (35, False),   # Seed, 8 people, no compliance pressure
    "brickbox.example":  (12, False),   # furniture retailer, not SaaS
    "ghostco.example":   (0,  False),   # no website pages at all
}


def stub_llm(replies):
    """Fake llm.ask: replies[step] is a dict or a list returned in order."""
    calls = []

    def ask(step, domain, prompt):
        calls.append(step)
        r = replies[step]
        return dict(r.pop(0) if isinstance(r, list) else r)
    return ask, calls


class TestCompanies(unittest.TestCase):
    """The real offline pipeline on each fixture company: fetch -> extract -> qualify."""

    def test_each_company(self):
        for domain, (score, qualified) in EXPECTED.items():
            with self.subTest(domain=domain):
                text = scrape.fetch(domain)
                company = extract.extract(domain, text) if text else {}
                if not company:
                    self.assertEqual(score, 0)          # ghostco: run.py treats as "no data"
                    continue
                r = qualify.qualify(domain, company)
                self.assertEqual(r["score"], score)
                self.assertEqual(r["qualified"], qualified)

    def test_full_run_only_emails_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            domains = list(EXPECTED)
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch("builtins.print"):
                    run.run(domains, str(ROOT / "data" / "contacts.csv"))
                drafted = sorted(p.stem for p in Path("outbox").glob("*.txt"))
                rows = [json.loads(l) for l in Path("runs/run_log.jsonl").read_text().splitlines()]
            finally:
                os.chdir(cwd)
        self.assertEqual(drafted, sorted(d for d, (_, q) in EXPECTED.items() if q))
        self.assertEqual(len(rows), len(domains))


class TestThreshold(unittest.TestCase):
    def check(self, score, expect):
        ask, _ = stub_llm({"qualify": {"score": score, "reason": "", "needs_more": False}})
        with mock.patch.object(llm, "ask", ask):
            return self.assertEqual(qualify.qualify("x", {})["qualified"], expect)

    def test_boundary(self):
        self.check(70, True)
        self.check(69, False)

    def test_low_scores_rejected(self):          # old bug: threshold 0.7 let these through
        self.check(12, False)
        self.check(1, False)

    def test_string_and_fraction_scores(self):
        self.check("86", True)                   # model returned a string
        self.check(0.82, True)                   # model used a 0-1 scale -> 82

    def test_missing_fields_dont_crash(self):
        ask, _ = stub_llm({"qualify": {}})
        with mock.patch.object(llm, "ask", ask):
            r = qualify.qualify("x", {})
        self.assertFalse(r["qualified"])


class TestMaxRounds(unittest.TestCase):
    UNSURE = {"score": 60, "reason": "unsure", "needs_more": True}

    def run_q(self, max_rounds, fetch=lambda d, p: f"page {p}", replies=None):
        ask, calls = stub_llm(replies or {"qualify": self.UNSURE, "qualify_more": self.UNSURE,
                                          "extract": {"stage": "Series B"}})
        with mock.patch.object(llm, "ask", ask), mock.patch.object(scrape, "fetch", fetch), \
             mock.patch.object(config, "MAX_ROUNDS", max_rounds):
            return qualify.qualify("x", {"company": "X"}), calls

    def test_rounds_equal_max_rounds(self):      # old bug: capped at 1 by the page list
        for n in (0, 1, 2, 3):
            with self.subTest(max_rounds=n):
                r, calls = self.run_q(n)
                self.assertEqual(r["rounds"], n)
                self.assertEqual(calls.count("qualify_more"), n)

    def test_still_unsure_is_not_qualified(self):
        r, _ = self.run_q(2, replies={"qualify": self.UNSURE, "extract": {},
                                      "qualify_more": {"score": 95, "needs_more": True}})
        self.assertTrue(r["incomplete"])
        self.assertFalse(r["qualified"])

    def test_missing_pages_skipped_without_using_a_round(self):
        r, _ = self.run_q(2, fetch=lambda d, p: "" if p in ("about", "security") else f"page {p}")
        self.assertEqual(r["rounds"], 2)
        self.assertEqual(r["pages_tried"], ["about", "security", "trust", "customers"])

    def test_stops_when_model_is_satisfied(self):
        r, _ = self.run_q(2, replies={"qualify": self.UNSURE, "extract": {},
                                      "qualify_more": {"score": 85, "needs_more": False}})
        self.assertEqual(r["rounds"], 1)
        self.assertTrue(r["qualified"])

    def test_runs_out_of_pages(self):
        r, _ = self.run_q(10)
        self.assertEqual(r["rounds"], len(qualify.EXTRA_PAGES))

    def test_merge_keeps_known_values(self):
        r = qualify._merge({"stage": "Series B", "signals": ["a"]}, {"stage": None, "signals": ["b"]})
        self.assertEqual(r, {"stage": "Series B", "signals": ["a", "b"]})

    def test_rescore_failure_keeps_last_answer(self):
        def ask(step, d, p):
            if step == "qualify_more":
                raise RuntimeError("model down")
            return {} if step == "extract" else {"score": 80, "reason": "r", "needs_more": True}
        with mock.patch.object(llm, "ask", ask), mock.patch.object(scrape, "fetch", lambda d, p: "t"):
            r = qualify.qualify("x", {})
        self.assertTrue(r["incomplete"])
        self.assertFalse(r["qualified"])


def resp(status, text=""):
    return types.SimpleNamespace(status_code=status, text=text)


@mock.patch.object(config, "RETRY_BACKOFF", 0)
@mock.patch.object(config, "OFFLINE", False)
class TestFetchRetry(unittest.TestCase):
    PAGE = "<p>" + "compliance " * 10 + "</p>"

    def fetch_with(self, responses):
        seq, calls = list(responses), []

        def get(url, **kw):
            calls.append(url)
            r = seq.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(requests, "get", get), mock.patch("builtins.print"):
            return scrape.fetch("x.example", "about"), len(calls)

    def test_timeout_then_success(self):
        text, n = self.fetch_with([requests.Timeout(), requests.Timeout(), resp(200, self.PAGE)])
        self.assertEqual(n, 3)
        self.assertIn("compliance", text)

    def test_gives_up_after_retries(self):
        text, n = self.fetch_with([resp(503)] * 5)
        self.assertEqual((text, n), ("", config.RETRIES + 1))

    def test_404_not_retried(self):
        self.assertEqual(self.fetch_with([resp(404)]), ("", 1))

    def test_html_tags_stripped(self):
        text, _ = self.fetch_with([resp(200, "<script>var a = 1 2 3 4 5 6 7 8;</script>" + self.PAGE)])
        self.assertNotIn("<", text)
        self.assertNotIn("var a", text)


@mock.patch.object(config, "RETRY_BACKOFF", 0)
@mock.patch.object(config, "OFFLINE", False)
@mock.patch.object(config, "API_KEY", "test-key")
class TestLlmRetry(unittest.TestCase):
    def ask_with(self, texts):
        seq, calls = list(texts), []

        def generate_content(**kw):
            calls.append(kw)
            return types.SimpleNamespace(text=seq.pop(0))
        genai = types.SimpleNamespace(Client=lambda api_key: types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=generate_content)))
        with mock.patch.dict(sys.modules, {"google": types.SimpleNamespace(genai=genai),
                                           "google.genai": genai}):
            return llm.ask("qualify", "x", "prompt"), calls

    def test_bad_json_then_fenced_json(self):
        r, calls = self.ask_with(["not json", '```json\n{"score": 77}\n```'])
        self.assertEqual(r, {"score": 77})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["config"]["response_mime_type"], "application/json")

    def test_gives_up_after_retries(self):
        with self.assertRaises(RuntimeError):
            self.ask_with(["bad"] * (config.RETRIES + 1))

    def test_no_api_key(self):
        with mock.patch.object(config, "API_KEY", None), self.assertRaises(RuntimeError):
            llm.ask("qualify", "x", "p")


if __name__ == "__main__":
    unittest.main()
