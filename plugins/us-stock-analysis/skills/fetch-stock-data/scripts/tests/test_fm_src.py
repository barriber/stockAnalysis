"""Tests for sources/fm_src.py — extraction logic, dispatch, auth, and HTTP error handling."""
from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from sources import fm_src  # noqa: E402


# ---------- Fixtures (representative slices of real FM responses) ----------

PRICES_FIXTURE = {
    "ticker": "INTC",
    "price": 99.62,
    "previousClose": 98.50,
    "change": 1.12,
    "changePercent": 1.137,
    "volume": 45_123_456,
    "marketCap": 506_399_460_000.0,
    "name": "Intel Corp.",
    "trailingPE": 18.4,
    "priceToFCF": None,
    "beta": 1.35,
    "eps": 5.41,
    "high52w": 110.50,
    "low52w": 78.10,
    "avgVolume": 50_000_000,
    "dividendYield": 0.012,
}

OVERVIEW_FIXTURE = {
    "company": {"name": "Intel Corp.", "ticker": "INTC"},
    "price": {"current": 99.62, "change": 1.12, "changePercent": 1.137, "currency": "USD"},
    "stats": {
        "marketCap": 506_399_460_000.0,
        "pe": 18.4,
        "eps": 5.41,
        "high52w": 110.5,
        "low52w": 78.1,
        "volume": 45_123_456,
        "avgVolume": 50_000_000,
        "dividendYield": 0.012,
        "beta": 1.35,
        "forwardPE": 14.2,
        "returnOnAssets": 0.045,
        "currentDebt": 4_000_000_000.0,
        "otherShortTermInvestments": 8_000_000_000.0,
        "stockholdersEquity": 105_000_000_000.0,
        "payoutRatio": 0.41,
        "heldPercentInstitutions": 0.62,
        "heldPercentInsiders": 0.001,
        "shortPercentOfFloat": 0.018,
        "shortRatio": 1.4,
    },
    "ratios": {"pfcf": 22.0, "fcfMargin": 0.18, "roic": 0.11, "fcfYield": 0.045, "roe": 0.16, "peg": 1.6},
    "trends": {
        "revenue":   {"history": [{"year": "2022", "value": 50_000_000_000}, {"year": "2023", "value": 54_000_000_000}], "isGrowing": True, "latestYoYPercent": 8.0},
        "netIncome": {"history": [{"year": "2023", "value": 8_000_000_000}], "isGrowing": True, "latestYoYPercent": 5.0},
        "fcf":       {"history": [{"year": "2023", "value": -3_120_000_000}], "isGrowing": False, "latestYoYPercent": -10.0},
        "shares":    {"history": [{"year": "2023", "value": 5_083_000_000}], "isGrowing": False, "latestYoYPercent": 0.5},
        "debt":      {"history": [{"year": "2023", "value": 41_000_000_000}], "isGrowing": False, "latestYoYPercent": 0.0},
    },
    "margins": {
        "gross":     [{"year": "2023", "value": None}],
        "operating": [{"year": "2023", "value": 22.5}],
        "net":       [{"year": "2023", "value": 14.8}],
    },
    "ttm": {
        "grossProfit": 30_000_000_000.0,
        "operatingIncome": 12_000_000_000.0,
        "taxProvision": 2_500_000_000.0,
        "pretaxIncome": 10_500_000_000.0,
        "effectiveTaxRate": 0.21,
        "stockBasedCompensation": 3_500_000_000.0,
        "asOf": "2025-12-31",
    },
    "growth": {
        "revenueCagr3y": 0.07,
        "revenueCagr5y": 0.09,
        "revenueCagr10y": 0.04,
        "dilutedEpsCagr5y": 0.12,
        "dividendCagr5y": 0.05,
    },
}

ANALYST_FIXTURE = {
    "ticker": "INTC",
    "asOf": "2026-05-02",
    "targetMeanPrice": 105.5,
    "targetHighPrice": 130.0,
    "targetLowPrice": 80.0,
    "numberOfAnalystOpinions": 38,
    "recommendationKey": "buy",
    "revenueEstimate2y": 70_000_000_000.0,
    "earningsEstimate2y": 6.8,
}

SEGMENTS_FIXTURE = {
    "ticker": "INTC",
    "asOf": "2025-12-31",
    "revenueProductSegmentation": {
        "Client Computing Group": 30_000_000_000.0,
        "Data Center & AI": 14_000_000_000.0,
    },
    "source": "fmp",
}

MACRO_FIXTURE = {
    "riskFreeRate": 0.0438,
    "equityRiskPremium": 0.055,
    "asOf": "2026-05-02",
    "sources": {"riskFreeRate": "fred:DGS10", "equityRiskPremium": "static:damodaran"},
}


# ---------- Extraction logic tests (no network) ----------

class ExtractPricesTests(unittest.TestCase):
    def test_full_field_set(self):
        out = fm_src._extract_prices(PRICES_FIXTURE, {
            "price", "change", "change_pct", "volume", "52w_high", "52w_low",
            "market_cap", "ttm_eps", "pe_ttm", "beta", "div_yield",
        })
        self.assertEqual(out["price"]["v"], 99.62)
        self.assertEqual(out["price"]["src"], "fm")
        self.assertEqual(out["price"]["c"], 1.0)
        self.assertEqual(out["change_pct"]["v"], 1.137)
        self.assertEqual(out["52w_high"]["v"], 110.5)
        self.assertEqual(out["52w_low"]["v"], 78.1)
        self.assertEqual(out["market_cap"]["u"], "USD")
        self.assertEqual(out["beta"]["c"], 0.9)

    def test_skips_unrequested_fields(self):
        out = fm_src._extract_prices(PRICES_FIXTURE, {"price"})
        self.assertEqual(set(out.keys()), {"price"})

    def test_missing_value_skipped(self):
        out = fm_src._extract_prices({"price": None}, {"price"})
        self.assertEqual(out, {})


class ExtractOverviewTests(unittest.TestCase):
    def setUp(self):
        self.requested = {
            "ttm_gross_profit", "ttm_op_income", "ttm_tax_rate", "ttm_sbc",
            "ttm_revenue", "ttm_net_income", "ttm_fcf", "diluted_shares",
            "pe_fwd", "peg", "roe", "roa", "roic", "fcf_margin",
            "op_margin", "net_margin",
            "short_term_debt", "long_term_debt", "total_debt",
            "st_investments", "total_equity",
            "div_payout", "inst_ownership_pct", "insider_ownership_pct",
            "short_pct_float", "days_to_cover",
            "rev_cagr_3y", "rev_cagr_5y", "rev_cagr_10y", "eps_cagr_5y", "div_growth_5y",
        }
        self.out = fm_src._extract_overview(OVERVIEW_FIXTURE, self.requested)

    def test_ttm_income(self):
        self.assertAlmostEqual(self.out["ttm_gross_profit"]["v"], 30_000.0)
        self.assertEqual(self.out["ttm_gross_profit"]["u"], "M_USD")
        self.assertAlmostEqual(self.out["ttm_op_income"]["v"], 12_000.0)
        self.assertAlmostEqual(self.out["ttm_tax_rate"]["v"], 0.21)
        self.assertAlmostEqual(self.out["ttm_sbc"]["v"], 3_500.0)

    def test_trends_latest_annual(self):
        self.assertAlmostEqual(self.out["ttm_revenue"]["v"], 54_000.0)
        self.assertEqual(self.out["ttm_revenue"]["note"], "latest annual")
        self.assertAlmostEqual(self.out["ttm_net_income"]["v"], 8_000.0)
        self.assertAlmostEqual(self.out["ttm_fcf"]["v"], -3_120.0)
        self.assertAlmostEqual(self.out["diluted_shares"]["v"], 5_083.0)

    def test_ratios_and_returns(self):
        self.assertAlmostEqual(self.out["pe_fwd"]["v"], 14.2)
        self.assertAlmostEqual(self.out["peg"]["v"], 1.6)
        self.assertAlmostEqual(self.out["roe"]["v"], 0.16)
        self.assertAlmostEqual(self.out["roa"]["v"], 0.045)
        self.assertAlmostEqual(self.out["roic"]["v"], 0.11)
        self.assertAlmostEqual(self.out["fcf_margin"]["v"], 0.18)

    def test_margins_converted_to_decimals(self):
        self.assertAlmostEqual(self.out["op_margin"]["v"], 0.225)
        self.assertAlmostEqual(self.out["net_margin"]["v"], 0.148)

    def test_balance_sheet_and_derived_total_debt(self):
        self.assertAlmostEqual(self.out["short_term_debt"]["v"], 4_000.0)
        self.assertAlmostEqual(self.out["st_investments"]["v"], 8_000.0)
        self.assertAlmostEqual(self.out["total_equity"]["v"], 105_000.0)
        self.assertAlmostEqual(self.out["long_term_debt"]["v"], 41_000.0)
        self.assertAlmostEqual(self.out["total_debt"]["v"], 4_000.0 + 41_000.0)
        self.assertEqual(self.out["total_debt"]["src"], "derived")

    def test_ownership_and_short(self):
        self.assertAlmostEqual(self.out["inst_ownership_pct"]["v"], 0.62)
        self.assertAlmostEqual(self.out["insider_ownership_pct"]["v"], 0.001)
        self.assertAlmostEqual(self.out["short_pct_float"]["v"], 0.018)
        self.assertAlmostEqual(self.out["days_to_cover"]["v"], 1.4)
        self.assertAlmostEqual(self.out["div_payout"]["v"], 0.41)

    def test_growth(self):
        self.assertAlmostEqual(self.out["rev_cagr_3y"]["v"], 0.07)
        self.assertAlmostEqual(self.out["rev_cagr_5y"]["v"], 0.09)
        self.assertAlmostEqual(self.out["rev_cagr_10y"]["v"], 0.04)
        self.assertAlmostEqual(self.out["eps_cagr_5y"]["v"], 0.12)
        self.assertAlmostEqual(self.out["div_growth_5y"]["v"], 0.05)

    def test_no_total_debt_when_one_leg_missing(self):
        body = {**OVERVIEW_FIXTURE, "stats": {**OVERVIEW_FIXTURE["stats"], "currentDebt": None}}
        out = fm_src._extract_overview(body, {"long_term_debt", "total_debt"})
        self.assertIn("long_term_debt", out)
        self.assertNotIn("total_debt", out)


class ExtractAnalystTests(unittest.TestCase):
    def test_fields_and_units(self):
        requested = {
            "analyst_pt_mean", "analyst_pt_high", "analyst_pt_low",
            "analyst_count", "analyst_revenue_2y", "analyst_eps_2y", "analyst_rating",
        }
        out = fm_src._extract_analyst(ANALYST_FIXTURE, requested)
        self.assertEqual(out["analyst_pt_mean"]["v"], 105.5)
        self.assertEqual(out["analyst_pt_high"]["v"], 130.0)
        self.assertEqual(out["analyst_pt_low"]["v"], 80.0)
        self.assertEqual(out["analyst_count"]["v"], 38)
        self.assertAlmostEqual(out["analyst_revenue_2y"]["v"], 70_000.0)
        self.assertEqual(out["analyst_revenue_2y"]["u"], "M_USD")
        self.assertEqual(out["analyst_eps_2y"]["v"], 6.8)
        self.assertEqual(out["analyst_rating"]["v"], "buy")


class ExtractSegmentsTests(unittest.TestCase):
    def test_segment_revenue_passes_through(self):
        out = fm_src._extract_segments(SEGMENTS_FIXTURE, {"segment_revenue"})
        self.assertIn("segment_revenue", out)
        self.assertEqual(out["segment_revenue"]["v"]["Client Computing Group"], 30_000_000_000.0)

    def test_empty_segments_skipped(self):
        out = fm_src._extract_segments({"revenueProductSegmentation": {}}, {"segment_revenue"})
        self.assertEqual(out, {})


class ExtractMacroTests(unittest.TestCase):
    def test_rf_rate_and_erp(self):
        out = fm_src._extract_macro(MACRO_FIXTURE, {"rf_rate", "erp"})
        self.assertAlmostEqual(out["rf_rate"]["v"], 0.0438)
        self.assertEqual(out["rf_rate"]["src"], "fm:fred")
        self.assertAlmostEqual(out["erp"]["v"], 0.055)
        self.assertEqual(out["erp"]["src"], "fm:damodaran")


# ---------- fetch() dispatch tests (mocked _get) ----------

class FetchDispatchTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.dict("os.environ", {"FINANCIAL_MANAGER_API_TOKEN": "fmt_pat_test"})
        self.token_patch.start()

    def tearDown(self):
        self.token_patch.stop()

    def test_routes_to_correct_endpoints(self):
        calls = []

        def fake_get(path):
            calls.append(path)
            if path.startswith("/api/prices/"):
                return PRICES_FIXTURE, None
            if path.startswith("/api/stocks/") and path.endswith("/overview"):
                return OVERVIEW_FIXTURE, None
            if path.startswith("/api/stocks/") and path.endswith("/analyst"):
                return ANALYST_FIXTURE, None
            if path.startswith("/api/stocks/") and path.endswith("/segments"):
                return SEGMENTS_FIXTURE, None
            if path == "/api/macro/rates":
                return MACRO_FIXTURE, None
            return None, f"unexpected path {path}"

        with patch.object(fm_src, "_get", side_effect=fake_get):
            out, errors = fm_src.fetch("INTC", [
                "price", "ttm_revenue", "analyst_pt_mean", "segment_revenue", "rf_rate",
            ])
        self.assertEqual(errors, [])
        self.assertIn("price", out)
        self.assertIn("ttm_revenue", out)
        self.assertIn("analyst_pt_mean", out)
        self.assertIn("segment_revenue", out)
        self.assertIn("rf_rate", out)
        self.assertEqual(set(calls), {
            "/api/prices/INTC",
            "/api/stocks/INTC/overview",
            "/api/stocks/INTC/analyst",
            "/api/stocks/INTC/segments",
            "/api/macro/rates",
        })

    def test_only_calls_endpoints_for_requested_groups(self):
        calls = []

        def fake_get(path):
            calls.append(path)
            return PRICES_FIXTURE, None

        with patch.object(fm_src, "_get", side_effect=fake_get):
            out, errors = fm_src.fetch("INTC", ["price"])
        self.assertEqual(calls, ["/api/prices/INTC"])
        self.assertIn("price", out)

    def test_propagates_endpoint_errors(self):
        def fake_get(path):
            return None, f"financial-manager HTTP 401 on {path}"

        with patch.object(fm_src, "_get", side_effect=fake_get):
            out, errors = fm_src.fetch("INTC", ["price"])
        self.assertEqual(out, {})
        self.assertTrue(any("HTTP 401" in e for e in errors))


class FetchAuthTests(unittest.TestCase):
    def test_missing_token_returns_structured_error(self):
        with patch.dict("os.environ", {}, clear=True):
            out, errors = fm_src.fetch("INTC", ["price"])
        self.assertEqual(out, {})
        self.assertTrue(any("FINANCIAL_MANAGER_API_TOKEN" in e for e in errors))


# ---------- _get HTTP error handling ----------


def _http_error(code: int, body: bytes = b""):
    return urllib.error.HTTPError("https://example.com", code, "msg", {}, io.BytesIO(body))


class GetHttpErrorTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.dict("os.environ", {"FINANCIAL_MANAGER_API_TOKEN": "fmt_pat_test"})
        self.token_patch.start()

    def tearDown(self):
        self.token_patch.stop()

    def _run_with_urlopen(self, raised):
        def fake_urlopen(req, timeout=None):
            raise raised

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            return fm_src._get("/api/prices/INTC")

    def test_401_returns_structured_error(self):
        body, err = self._run_with_urlopen(_http_error(401, b"Unauthorized"))
        self.assertIsNone(body)
        self.assertIn("HTTP 401", err)

    def test_404_returns_structured_error(self):
        body, err = self._run_with_urlopen(_http_error(404, b"Not Found"))
        self.assertIsNone(body)
        self.assertIn("HTTP 404", err)

    def test_5xx_returns_structured_error(self):
        body, err = self._run_with_urlopen(_http_error(503, b"unavailable"))
        self.assertIsNone(body)
        self.assertIn("HTTP 503", err)

    def test_url_error_returns_structured_error(self):
        body, err = self._run_with_urlopen(urllib.error.URLError("name resolution failed"))
        self.assertIsNone(body)
        self.assertIn("URL error", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
