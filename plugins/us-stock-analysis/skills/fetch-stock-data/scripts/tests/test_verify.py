"""Offline tests for verify.py — identity checks, sign checks, freshness, aggregate confidence."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify  # noqa: E402


class IdentityTests(unittest.TestCase):
    def test_fcf_identity_passes_within_tolerance(self):
        data = {
            "ttm_ocf":   {"v": 9980.0},
            "ttm_capex": {"v": 13100.0},
            "ttm_fcf":   {"v": -3120.0},
        }
        passed, failed, warnings = verify.run_identities(data)
        self.assertIn("fcf_identity", passed)
        self.assertNotIn("fcf_identity", failed)
        self.assertEqual(warnings, [])

    def test_fcf_identity_fails_outside_tolerance(self):
        data = {
            "ttm_ocf":   {"v": 10000.0},
            "ttm_capex": {"v": 5000.0},
            "ttm_fcf":   {"v": -3000.0},
        }
        passed, failed, _warnings = verify.run_identities(data)
        self.assertIn("fcf_identity", failed)
        self.assertNotIn("fcf_identity", passed)

    def test_market_cap_identity_passes(self):
        data = {
            "price":          {"v": 99.62},
            "diluted_shares": {"v": 5083.0},
            "market_cap":     {"v": 99.62 * 5083.0 * 1_000_000.0},
        }
        passed, _failed, _warns = verify.run_identities(data)
        self.assertIn("market_cap_identity", passed)

    def test_total_debt_identity(self):
        data = {
            "short_term_debt": {"v": 2004.0},
            "long_term_debt":  {"v": 43027.0},
            "total_debt":      {"v": 45031.0},
        }
        passed, _failed, _warns = verify.run_identities(data)
        self.assertIn("total_debt_identity", passed)

    def test_missing_inputs_skip_identity(self):
        data = {"ttm_ocf": {"v": 100.0}}
        passed, failed, warnings = verify.run_identities(data)
        self.assertEqual(passed, [])
        self.assertEqual(failed, [])
        self.assertEqual(warnings, [])


class MergeSourcesPassthroughTests(unittest.TestCase):
    def test_single_candidate_returned(self):
        merged, warns = verify.merge_sources("price", [{"v": 100.0, "src": "fm", "c": 1.0}])
        self.assertIsNotNone(merged)
        self.assertEqual(merged["v"], 100.0)
        self.assertEqual(merged["src"], "fm")
        self.assertEqual(warns, [])

    def test_no_candidates_returns_none(self):
        merged, warns = verify.merge_sources("price", [])
        self.assertIsNone(merged)
        self.assertEqual(warns, [])

    def test_default_confidence_when_missing(self):
        merged, _ = verify.merge_sources("price", [{"v": 100.0, "src": "fm"}])
        self.assertEqual(merged["c"], 0.9)


class FreshnessTests(unittest.TestCase):
    def test_fresh_price_passes(self):
        ts = datetime.now(timezone.utc) - timedelta(hours=2)
        data = {"price": {"v": 100.0, "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": 1.0}}
        passed, warnings = verify.check_freshness(data)
        self.assertIn("freshness_price", passed)
        self.assertEqual(warnings, [])

    def test_stale_price_warns(self):
        ts = datetime.now(timezone.utc) - timedelta(hours=48)
        data = {"price": {"v": 100.0, "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": 1.0}}
        passed, warnings = verify.check_freshness(data)
        self.assertNotIn("freshness_price", passed)
        self.assertTrue(any("stale" in w for w in warnings))
        self.assertTrue(data["price"].get("stale"))

    def test_very_stale_price_low_confidence(self):
        ts = datetime.now(timezone.utc) - timedelta(hours=200)
        data = {"price": {"v": 100.0, "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": 1.0}}
        _passed, warnings = verify.check_freshness(data)
        self.assertTrue(any("very stale" in w for w in warnings))
        self.assertEqual(data["price"]["c"], 0.4)


class SignCheckTests(unittest.TestCase):
    def test_negative_revenue_flagged(self):
        data = {"ttm_revenue": {"v": -100.0}}
        warnings = verify.check_signs(data)
        self.assertTrue(any("ttm_revenue" in w for w in warnings))

    def test_negative_fcf_not_flagged(self):
        data = {"ttm_fcf": {"v": -3000.0}}
        warnings = verify.check_signs(data)
        self.assertEqual([w for w in warnings if "ttm_fcf" in w], [])


class AggregateConfidenceTests(unittest.TestCase):
    def test_average(self):
        data = {
            "a": {"v": 1, "c": 1.0},
            "b": {"v": 2, "c": 0.8},
            "c": {"v": 3, "c": 0.6},
        }
        self.assertAlmostEqual(verify.aggregate_confidence(data), 0.8, places=2)

    def test_empty(self):
        self.assertEqual(verify.aggregate_confidence({}), 0.0)

    def test_skips_non_finite(self):
        data = {"a": {"v": 1, "c": float("nan")}, "b": {"v": 2, "c": 0.5}}
        self.assertEqual(verify.aggregate_confidence(data), 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
