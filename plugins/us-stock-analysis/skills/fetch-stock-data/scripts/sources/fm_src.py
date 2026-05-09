"""financial-manager source — single backend for fetch-stock-data.

Hits the user's deployed financial-manager Next.js app (default
`https://financial-manager-borisber87-4227s-projects.vercel.app`) using a
read-only API token (`Bearer fmt_pat_*`). Stdlib urllib only.

Endpoints used (all support API-token auth via `getApiAuth`):
  GET /api/prices/{ticker}
  GET /api/stocks/{ticker}/overview
  GET /api/stocks/{ticker}/analyst
  GET /api/stocks/{ticker}/segments
  GET /api/macro/rates

Fields not exposed by these endpoints today (cash, ttm_ocf/ttm_capex, pb, ps,
ev_ebitda, ev_fcf, gross_margin) are reported as missing by fetch.py — extend
financial-manager to surface them via API-token auth before adding routing.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


_DEFAULT_BASE = "https://financial-manager-borisber87-4227s-projects.vercel.app"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_url() -> str:
    return os.environ.get("FINANCIAL_MANAGER_BASE_URL", _DEFAULT_BASE).rstrip("/")


def _token() -> str | None:
    return os.environ.get("FINANCIAL_MANAGER_API_TOKEN")


def _get(path: str) -> tuple[Any, str | None]:
    url = f"{_base_url()}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {_token()}",
            "User-Agent": "fetch-stock-data/fm-client",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")[:200]
        except Exception:
            pass
        return None, f"financial-manager HTTP {exc.code} on {path}: {body}".strip()
    except urllib.error.URLError as exc:
        return None, f"financial-manager URL error on {path}: {exc.reason}"
    except json.JSONDecodeError as exc:
        return None, f"financial-manager non-JSON response on {path}: {exc}"


# Field groups → endpoint that supplies them.
PRICES_FIELDS = {
    "price", "change", "change_pct", "volume", "52w_high", "52w_low",
    "market_cap", "ttm_eps", "pe_ttm", "beta", "div_yield",
}
OVERVIEW_FIELDS = {
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
ANALYST_FIELDS = {
    "analyst_pt_mean", "analyst_pt_high", "analyst_pt_low",
    "analyst_count", "analyst_revenue_2y", "analyst_eps_2y", "analyst_rating",
}
SEGMENT_FIELDS = {"segment_revenue"}
MACRO_FIELDS = {"rf_rate", "erp"}


def fetch(ticker: str, fields: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not _token():
        return {}, [
            "FINANCIAL_MANAGER_API_TOKEN not set — generate a read-only token in financial-manager and "
            "export FINANCIAL_MANAGER_API_TOKEN=fmt_pat_..."
        ]

    requested = set(fields)
    out: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    if requested & PRICES_FIELDS:
        body, err = _get(f"/api/prices/{ticker}")
        if err:
            errors.append(err)
        elif isinstance(body, dict):
            out.update(_extract_prices(body, requested))

    if requested & OVERVIEW_FIELDS:
        body, err = _get(f"/api/stocks/{ticker}/overview")
        if err:
            errors.append(err)
        elif isinstance(body, dict):
            out.update(_extract_overview(body, requested))

    if requested & ANALYST_FIELDS:
        body, err = _get(f"/api/stocks/{ticker}/analyst")
        if err:
            errors.append(err)
        elif isinstance(body, dict):
            out.update(_extract_analyst(body, requested))

    if requested & SEGMENT_FIELDS:
        body, err = _get(f"/api/stocks/{ticker}/segments")
        if err:
            errors.append(err)
        elif isinstance(body, dict):
            out.update(_extract_segments(body, requested))

    if requested & MACRO_FIELDS:
        body, err = _get("/api/macro/rates")
        if err:
            errors.append(err)
        elif isinstance(body, dict):
            out.update(_extract_macro(body, requested))

    return out, errors


def _extract_prices(body: dict[str, Any], requested: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ts = _now_iso()

    def put(field: str, val: Any, *, unit: str | None = None, c: float = 0.95) -> None:
        if val is None:
            return
        try:
            v = float(val)
        except (TypeError, ValueError):
            return
        entry: dict[str, Any] = {"v": v, "src": "fm", "c": c, "ts": ts}
        if unit:
            entry["u"] = unit
        out[field] = entry

    if "price" in requested:
        put("price", body.get("price"), c=1.0)
    if "change" in requested:
        put("change", body.get("change"))
    if "change_pct" in requested:
        put("change_pct", body.get("changePercent"))
    if "volume" in requested:
        put("volume", body.get("volume"))
    if "52w_high" in requested:
        put("52w_high", body.get("high52w"))
    if "52w_low" in requested:
        put("52w_low", body.get("low52w"))
    if "market_cap" in requested:
        put("market_cap", body.get("marketCap"), unit="USD")
    if "ttm_eps" in requested:
        put("ttm_eps", body.get("eps"))
    if "pe_ttm" in requested:
        put("pe_ttm", body.get("trailingPE"))
    if "beta" in requested:
        put("beta", body.get("beta"), c=0.9)
    if "div_yield" in requested:
        put("div_yield", body.get("dividendYield"))
    return out


def _latest_history_value(trend: Any) -> tuple[float | None, str | None]:
    if not isinstance(trend, dict):
        return None, None
    history = trend.get("history")
    if not isinstance(history, list) or not history:
        return None, None
    last = history[-1]
    if not isinstance(last, dict):
        return None, None
    val = last.get("value")
    year = last.get("year")
    if val is None:
        return None, None
    try:
        return float(val), str(year) if year is not None else None
    except (TypeError, ValueError):
        return None, None


def _latest_margin(margins: Any, key: str) -> float | None:
    if not isinstance(margins, dict):
        return None
    arr = margins.get(key)
    if not isinstance(arr, list):
        return None
    for entry in reversed(arr):
        if isinstance(entry, dict) and entry.get("value") is not None:
            try:
                return float(entry["value"])
            except (TypeError, ValueError):
                return None
    return None


def _extract_overview(body: dict[str, Any], requested: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    stats = body.get("stats") or {}
    ratios = body.get("ratios") or {}
    ttm = body.get("ttm") or {}
    trends = body.get("trends") or {}
    margins = body.get("margins") or {}
    growth = body.get("growth") or {}
    asof = ttm.get("asOf")

    def num(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    # TTM income statement (USD).
    if "ttm_gross_profit" in requested:
        v = num(ttm.get("grossProfit"))
        if v is not None:
            out["ttm_gross_profit"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.95, "ts": asof}
    if "ttm_op_income" in requested:
        v = num(ttm.get("operatingIncome"))
        if v is not None:
            out["ttm_op_income"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.95, "ts": asof}
    if "ttm_tax_rate" in requested:
        v = num(ttm.get("effectiveTaxRate"))
        if v is not None:
            out["ttm_tax_rate"] = {"v": v, "src": "fm", "c": 0.95, "ts": asof}
    if "ttm_sbc" in requested:
        v = num(ttm.get("stockBasedCompensation"))
        if v is not None:
            out["ttm_sbc"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.95, "ts": asof}

    # Latest annual values used as "TTM" approximations.
    if "ttm_revenue" in requested:
        v, year = _latest_history_value(trends.get("revenue"))
        if v is not None:
            out["ttm_revenue"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.9, "ts": year, "note": "latest annual"}
    if "ttm_net_income" in requested:
        v, year = _latest_history_value(trends.get("netIncome"))
        if v is not None:
            out["ttm_net_income"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.9, "ts": year, "note": "latest annual"}
    if "ttm_fcf" in requested:
        v, year = _latest_history_value(trends.get("fcf"))
        if v is not None:
            out["ttm_fcf"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.9, "ts": year, "note": "latest annual"}
    if "diluted_shares" in requested:
        v, year = _latest_history_value(trends.get("shares"))
        if v is not None:
            out["diluted_shares"] = {"v": v / 1e6, "u": "M", "src": "fm", "c": 0.9, "ts": year}

    # Multiples / returns.
    if "pe_fwd" in requested:
        v = num(stats.get("forwardPE"))
        if v is not None:
            out["pe_fwd"] = {"v": v, "src": "fm", "c": 0.9}
    if "peg" in requested:
        v = num(ratios.get("peg"))
        if v is not None:
            out["peg"] = {"v": v, "src": "fm", "c": 0.9}
    if "roe" in requested:
        v = num(ratios.get("roe"))
        if v is not None:
            out["roe"] = {"v": v, "src": "fm", "c": 0.95}
    if "roa" in requested:
        v = num(stats.get("returnOnAssets"))
        if v is not None:
            out["roa"] = {"v": v, "src": "fm", "c": 0.95}
    if "roic" in requested:
        v = num(ratios.get("roic"))
        if v is not None:
            out["roic"] = {"v": v, "src": "fm", "c": 0.95}
    if "fcf_margin" in requested:
        v = num(ratios.get("fcfMargin"))
        if v is not None:
            out["fcf_margin"] = {"v": v, "src": "fm", "c": 0.95}

    # Margins (FM returns these as percentages for op/net; convert to decimals to match the rest of the catalog).
    if "op_margin" in requested:
        v = _latest_margin(margins, "operating")
        if v is not None:
            out["op_margin"] = {"v": v / 100.0, "src": "fm", "c": 0.9}
    if "net_margin" in requested:
        v = _latest_margin(margins, "net")
        if v is not None:
            out["net_margin"] = {"v": v / 100.0, "src": "fm", "c": 0.9}

    # Stats (USD or decimals).
    if "short_term_debt" in requested:
        v = num(stats.get("currentDebt"))
        if v is not None:
            out["short_term_debt"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.95, "ts": asof}
    if "st_investments" in requested:
        v = num(stats.get("otherShortTermInvestments"))
        if v is not None:
            out["st_investments"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.95, "ts": asof}
    if "total_equity" in requested:
        v = num(stats.get("stockholdersEquity"))
        if v is not None:
            out["total_equity"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.95, "ts": asof}
    if "div_payout" in requested:
        v = num(stats.get("payoutRatio"))
        if v is not None:
            out["div_payout"] = {"v": v, "src": "fm", "c": 0.95}
    if "inst_ownership_pct" in requested:
        v = num(stats.get("heldPercentInstitutions"))
        if v is not None:
            out["inst_ownership_pct"] = {"v": v, "src": "fm", "c": 0.9}
    if "insider_ownership_pct" in requested:
        v = num(stats.get("heldPercentInsiders"))
        if v is not None:
            out["insider_ownership_pct"] = {"v": v, "src": "fm", "c": 0.9}
    if "short_pct_float" in requested:
        v = num(stats.get("shortPercentOfFloat"))
        if v is not None:
            out["short_pct_float"] = {"v": v, "src": "fm", "c": 0.9}
    if "days_to_cover" in requested:
        v = num(stats.get("shortRatio"))
        if v is not None:
            out["days_to_cover"] = {"v": v, "src": "fm", "c": 0.9}

    # long_term_debt comes from trends.debt history (extractTrend uses longTermDebt).
    if "long_term_debt" in requested:
        v, year = _latest_history_value(trends.get("debt"))
        if v is not None:
            out["long_term_debt"] = {
                "v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.9, "ts": year,
                "note": "latest annual longTermDebt",
            }

    # total_debt = short_term_debt + long_term_debt (only if both present).
    if "total_debt" in requested and "short_term_debt" in out and "long_term_debt" in out:
        out["total_debt"] = {
            "v": out["short_term_debt"]["v"] + out["long_term_debt"]["v"],
            "u": "M_USD", "src": "derived", "c": 0.85, "note": "short_term + long_term",
        }

    # Growth (decimals).
    growth_map = {
        "rev_cagr_3y": "revenueCagr3y",
        "rev_cagr_5y": "revenueCagr5y",
        "rev_cagr_10y": "revenueCagr10y",
        "eps_cagr_5y": "dilutedEpsCagr5y",
        "div_growth_5y": "dividendCagr5y",
    }
    for field, key in growth_map.items():
        if field not in requested:
            continue
        v = num(growth.get(key))
        if v is not None:
            out[field] = {"v": v, "src": "fm", "c": 0.95}

    return out


def _extract_analyst(body: dict[str, Any], requested: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    asof = body.get("asOf")

    def num(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    if "analyst_pt_mean" in requested:
        v = num(body.get("targetMeanPrice"))
        if v is not None:
            out["analyst_pt_mean"] = {"v": v, "src": "fm", "c": 0.9, "ts": asof}
    if "analyst_pt_high" in requested:
        v = num(body.get("targetHighPrice"))
        if v is not None:
            out["analyst_pt_high"] = {"v": v, "src": "fm", "c": 0.9, "ts": asof}
    if "analyst_pt_low" in requested:
        v = num(body.get("targetLowPrice"))
        if v is not None:
            out["analyst_pt_low"] = {"v": v, "src": "fm", "c": 0.9, "ts": asof}
    if "analyst_count" in requested:
        v = body.get("numberOfAnalystOpinions")
        if v is not None:
            try:
                out["analyst_count"] = {"v": int(v), "src": "fm", "c": 0.9, "ts": asof}
            except (TypeError, ValueError):
                pass
    if "analyst_revenue_2y" in requested:
        v = num(body.get("revenueEstimate2y"))
        if v is not None:
            out["analyst_revenue_2y"] = {"v": v / 1e6, "u": "M_USD", "src": "fm", "c": 0.85, "ts": asof}
    if "analyst_eps_2y" in requested:
        v = num(body.get("earningsEstimate2y"))
        if v is not None:
            out["analyst_eps_2y"] = {"v": v, "src": "fm", "c": 0.85, "ts": asof}
    if "analyst_rating" in requested:
        v = body.get("recommendationKey")
        if v is not None:
            out["analyst_rating"] = {"v": str(v), "src": "fm", "c": 0.9, "ts": asof}
    return out


def _extract_segments(body: dict[str, Any], requested: set[str]) -> dict[str, dict[str, Any]]:
    if "segment_revenue" not in requested:
        return {}
    seg = body.get("revenueProductSegmentation")
    if not isinstance(seg, dict) or not seg:
        return {}
    return {
        "segment_revenue": {
            "v": seg, "u": "USD", "src": "fm", "c": 0.9, "ts": body.get("asOf"),
        }
    }


def _extract_macro(body: dict[str, Any], requested: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    asof = body.get("asOf")

    rf = body.get("riskFreeRate")
    if "rf_rate" in requested and rf is not None:
        try:
            out["rf_rate"] = {"v": float(rf), "src": "fm:fred", "c": 1.0, "ts": asof}
        except (TypeError, ValueError):
            pass

    erp = body.get("equityRiskPremium")
    if "erp" in requested and erp is not None:
        try:
            out["erp"] = {"v": float(erp), "src": "fm:damodaran", "c": 0.7, "note": "Damodaran static"}
        except (TypeError, ValueError):
            pass
    return out
