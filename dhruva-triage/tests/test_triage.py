"""Tests for dhruva-triage: scoring, cost, anti-thesis guard, loader and the end-to-end run.

Run from the project folder:   .venv\Scripts\python -m unittest discover -s tests -v
No network or paid API calls: OFFLINE fixtures only.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
config.OFFLINE = True
import cost, guard, loader, run, score  # noqa: E402

# Expected outcome per application, given fixtures/llm_responses.json.
EXPECTED = {
    "A01": (3.3, "PASS"),                              # Series B, US: not thesis
    "A02": (0.8, "INSUFFICIENT DATA TO RECOMMEND"),    # 5 of 6 criteria unknown
    "A03": (7.5, "ADVANCE TO CALL"),                   # strong fit, round size unknown
    "A04": (5.0, "PASS (anti-thesis: d2c)"),
    "A05": (7.5, "PASS (anti-thesis: nbfc)"),
    "A06": (10.0, "ADVANCE TO CALL"),
}


def v(verdict, citation="x"):
    return {"verdict": verdict, "citation": citation}


class Score(unittest.TestCase):
    def test_insufficient_data_scores_zero_not_one(self):
        verdicts = {c: v("insufficient-data", None) for c in config.CRITERIA}
        self.assertEqual(score.raw_score(verdicts), 0)

    def test_fit_is_absolute_not_relative_to_batch(self):
        weak = score.normalise({c: v("no-match") for c in config.CRITERIA[:4]}
                               | {c: v("match") for c in config.CRITERIA[4:]})
        self.assertEqual(score.fit_score(weak), 3.3)

    def test_skipped_unknown_or_uncited_criteria_become_missing(self):
        out = score.normalise({"stage": v("match"), "sector": v("great"),
                               "geography": v("match", None)})
        self.assertEqual(set(out), set(config.CRITERIA))
        self.assertEqual(score.missing(out), config.CRITERIA[1:])

    def test_recommend_thresholds(self):
        self.assertEqual(score.recommend(7.0, 0, None), "ADVANCE TO CALL")
        self.assertEqual(score.recommend(6.9, 0, None), "PASS")
        self.assertEqual(score.recommend(10, 4, None), "INSUFFICIENT DATA TO RECOMMEND")
        self.assertEqual(score.recommend(10, 0, "d2c"), "PASS (anti-thesis: d2c)")


class Cost(unittest.TestCase):
    def test_returns_rupees(self):
        # 1M in + 1M out = $10 = Rs 850 at the illustrative rate
        self.assertAlmostEqual(cost.cost_inr(1_000_000, 1_000_000), 10 * cost.USD_INR)


class Guard(unittest.TestCase):
    def app(self, sector, model=""):
        return {"sector": sector, "model": model}

    def test_hits(self):
        self.assertEqual(guard.anti_thesis(self.app("D2C snack brand")), "d2c")
        self.assertEqual(guard.anti_thesis(self.app("lending (needs NBFC licence)")), "nbfc")

    def test_whole_word_only(self):
        self.assertIsNone(guard.anti_thesis(self.app("B2B software", "annual SaaS contract")))
        self.assertIsNone(guard.anti_thesis(self.app("cryptography tooling for banks")))


class Loader(unittest.TestCase):
    def test_header_with_trailing_space_loads(self):
        apps = loader.load(str(ROOT / "data" / "applications_v2.csv"))
        self.assertEqual([a["id"] for a in apps], list(EXPECTED))
        self.assertEqual(apps[0]["round_size_cr"], "80")

    def test_missing_column_is_a_clear_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("id,name\nA01,StoryPal\n")
        try:
            with self.assertRaisesRegex(ValueError, "missing column"):
                loader.load(f.name)
        finally:
            os.unlink(f.name)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_file(self, name):
        return {r["id"]: r for r in run.run(str(ROOT / "data" / name))}

    def test_expected_recommendations(self):
        rows = self.run_file("applications.csv")
        self.assertEqual({k: (r["fit"], r["rec"]) for k, r in rows.items()}, EXPECTED)
        self.assertEqual(rows["A03"]["could_not_establish"], ["round_size"])

    def test_result_does_not_depend_on_row_order(self):
        a = self.run_file("applications.csv")
        src = (ROOT / "data" / "applications.csv").read_text(encoding="utf-8").splitlines()
        Path("rev.csv").write_text("\n".join([src[0]] + src[1:][::-1]) + "\n", encoding="utf-8")
        b = {r["id"]: r for r in run.run("rev.csv")}
        self.assertEqual({k: r["fit"] for k, r in a.items()}, {k: r["fit"] for k, r in b.items()})

    def test_cost_is_in_rupees_and_flags_ceiling(self):
        rows = self.run_file("applications.csv")
        self.assertGreater(rows["A06"]["cost_inr"], config.COST_CEILING_INR)
        self.assertTrue(all(r["over_ceiling"] for r in rows.values()))


if __name__ == "__main__":
    unittest.main()
