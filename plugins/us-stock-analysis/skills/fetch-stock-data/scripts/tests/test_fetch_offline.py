"""Offline integration tests for fetch.py — using monkey-patched ROUTING.

Verifies end-to-end behavior without network: routing, market_cap derivation, identity
verification, missing fields, unsupported fields, and the JSON envelope contract.
"""
from __future__ import annotations

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch as fetch_mod  # noqa: E402


def _stub_source(payload: dict[str, dict], errors: list[str] | None = None):
    class _Stub:
        __name__ = "stub_src"

        @staticmethod
        def fetch(ticker, fields):
            return ({k: v for k, v in payload.items() if k in fields}, errors or [])

    return _Stub


class FetchEndToEndTests(unittest.TestCase):
    def _run(self, fields: str, routing_overrides: dict) -> tuple[int, dict]:
        with patch.dict(fetch_mod.ROUTING, routing_overrides, clear=False), \
             patch("sys.stdout", new=StringIO()) as out:
            rc = fetch_mod.main([
                "--ticker", "INTC",
                "--fields", fields,
                "--verify", "strict",
            ])
            return rc, json.loads(out.getvalue())

    def test_basic_envelope_shape(self):
        stub = _stub_source({
            "price":          {"v": 99.62, "src": "fm", "ts": "2026-05-02T15:00:00Z", "c": 1.0},
            "diluted_shares": {"v": 5083.0, "u": "M", "src": "fm", "c": 0.9},
        })
        rc, env = self._run("price,diluted_shares", {"price": [stub], "diluted_shares": [stub]})
        self.assertEqual(rc, 0)
        self.assertEqual(env["ticker"], "INTC")
        self.assertIn("data", env)
        self.assertIn("verification", env)
        self.assertIn("missing", env)
        self.assertEqual(env["data"]["price"]["v"], 99.62)
        self.assertEqual(env["data"]["diluted_shares"]["v"], 5083.0)
        self.assertEqual(env["missing"], [])

    def test_missing_field_listed(self):
        stub = _stub_source({"price": {"v": 100.0, "src": "fm"}})
        empty = _stub_source({})
        rc, env = self._run("price,ttm_revenue", {"price": [stub], "ttm_revenue": [empty]})
        self.assertIn("ttm_revenue", env["missing"])
        self.assertNotIn("price", env["missing"])

    def test_unsupported_field_marked_missing_with_error(self):
        stub = _stub_source({"price": {"v": 100.0, "src": "fm", "ts": "2026-05-02T15:00:00Z"}})
        rc, env = self._run("price,pb,ttm_ocf", {"price": [stub]})
        self.assertEqual(rc, 3)
        self.assertIn("pb", env["missing"])
        self.assertIn("ttm_ocf", env["missing"])
        joined = " ".join(env["errors"])
        self.assertIn("field_unsupported_by_fm", joined)
        self.assertIn("pb:", joined)
        self.assertIn("ttm_ocf:", joined)

    def test_market_cap_derivation(self):
        stub = _stub_source({
            "price":          {"v": 100.0, "src": "fm", "ts": "2026-05-02T15:00:00Z"},
            "diluted_shares": {"v": 5000.0, "u": "M", "src": "fm"},
        })
        rc, env = self._run("market_cap", {
            "price":          [stub],
            "diluted_shares": [stub],
            "market_cap":     [_stub_source({})],
        })
        self.assertEqual(env["data"]["market_cap"]["src"], "derived")
        self.assertAlmostEqual(env["data"]["market_cap"]["v"], 100.0 * 5000.0 * 1_000_000.0, places=1)

    def test_market_cap_identity(self):
        stub = _stub_source({
            "price":          {"v": 100.0, "src": "fm", "ts": "2026-05-02T15:00:00Z"},
            "diluted_shares": {"v": 5000.0, "u": "M", "src": "fm"},
            "market_cap":     {"v": 100.0 * 5000.0 * 1_000_000.0, "u": "USD", "src": "fm"},
        })
        rc, env = self._run("price,diluted_shares,market_cap", {
            "price":          [stub],
            "diluted_shares": [stub],
            "market_cap":     [stub],
        })
        self.assertIn("market_cap_identity", env["verification"]["passed"])

    def test_total_debt_identity(self):
        stub = _stub_source({
            "short_term_debt": {"v": 2000.0, "u": "M_USD", "src": "fm"},
            "long_term_debt":  {"v": 43000.0, "u": "M_USD", "src": "fm"},
            "total_debt":      {"v": 45000.0, "u": "M_USD", "src": "fm"},
        })
        rc, env = self._run("short_term_debt,long_term_debt,total_debt", {
            "short_term_debt": [stub],
            "long_term_debt":  [stub],
            "total_debt":      [stub],
        })
        self.assertIn("total_debt_identity", env["verification"]["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
