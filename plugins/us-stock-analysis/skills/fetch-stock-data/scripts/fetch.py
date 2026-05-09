#!/usr/bin/env python3
"""fetch.py — entry point for the fetch-stock-data internal skill.

Talks to the user's financial-manager Next.js app (single backend), runs identity
+ freshness verification, and prints a single compact JSON envelope on stdout.

Exit codes:
  0  success (output on stdout)
  2  unrecoverable error before fetch could run (output on stderr)
  3  partial failure: some fields missing or backend unreachable (envelope still on stdout)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import verify  # noqa: E402
from sources import fm_src  # noqa: E402


# Field → list of source modules. financial-manager is the only backend.
ROUTING: dict[str, list] = {
    # Price / market data
    "price":           [fm_src],
    "change":          [fm_src],
    "change_pct":      [fm_src],
    "volume":          [fm_src],
    "52w_high":        [fm_src],
    "52w_low":         [fm_src],
    "market_cap":      [fm_src],

    # Income (TTM)
    "ttm_revenue":     [fm_src],
    "ttm_gross_profit":[fm_src],
    "ttm_op_income":   [fm_src],
    "ttm_net_income":  [fm_src],
    "ttm_eps":         [fm_src],
    "ttm_tax_rate":    [fm_src],

    # Cash flow (TTM) — fcf is exposed; ocf/capex are NOT (see UNSUPPORTED_FIELDS)
    "ttm_fcf":         [fm_src],
    "ttm_sbc":         [fm_src],

    # Balance sheet
    "short_term_debt": [fm_src],
    "long_term_debt":  [fm_src],
    "total_debt":      [fm_src],   # derived inside fm_src from short + long
    "st_investments":  [fm_src],
    "total_equity":    [fm_src],
    "diluted_shares":  [fm_src],

    # Margins / returns / multiples
    "op_margin":       [fm_src],
    "net_margin":      [fm_src],
    "fcf_margin":      [fm_src],
    "pe_ttm":          [fm_src],
    "pe_fwd":          [fm_src],
    "peg":             [fm_src],
    "roe":             [fm_src],
    "roa":             [fm_src],
    "roic":            [fm_src],

    # Risk
    "beta":            [fm_src],
    "rf_rate":         [fm_src],
    "erp":             [fm_src],

    # Analyst consensus
    "analyst_pt_mean":   [fm_src],
    "analyst_pt_high":   [fm_src],
    "analyst_pt_low":    [fm_src],
    "analyst_count":     [fm_src],
    "analyst_revenue_2y":[fm_src],
    "analyst_eps_2y":    [fm_src],
    "analyst_rating":    [fm_src],

    # Dividends
    "div_yield":       [fm_src],
    "div_payout":      [fm_src],
    "div_growth_5y":   [fm_src],

    # Other
    "segment_revenue":      [fm_src],
    "inst_ownership_pct":   [fm_src],
    "insider_ownership_pct":[fm_src],
    "short_pct_float":      [fm_src],
    "days_to_cover":        [fm_src],
}


# Catalog fields that financial-manager does not currently expose via API-token endpoints.
# Requesting any of these returns a structured entry in the envelope's `errors[]` and
# leaves the field in `missing[]` until financial-manager surfaces it.
UNSUPPORTED_FIELDS = {
    "pb", "ps", "ev_ebitda", "ev_fcf",
    "ttm_ocf", "ttm_capex",
    "cash", "net_debt",
    "gross_margin",
}


# Fields derivable from others when missing. ttm_fcf / fcf_margin come from fm_src
# directly, so the only useful derivation here is market_cap (price × shares).
DERIVATIONS = {
    "market_cap":  ("price * diluted_shares", lambda d: _derive_market_cap(d)),
}


def _derive_market_cap(data: dict) -> dict | None:
    price = data.get("price", {}).get("v")
    shares = data.get("diluted_shares", {}).get("v")
    if price is None or shares is None:
        return None
    return {"v": price * shares * 1_000_000.0, "u": "USD", "src": "derived", "c": 0.9, "note": "price * shares"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gather(ticker: str, fields: list[str]) -> tuple[dict, list[str], list[str]]:
    """Returns (data, missing, errors)."""
    data: dict[str, dict] = {}
    errors: list[str] = []
    missing: list[str] = []

    supported = [f for f in fields if f not in UNSUPPORTED_FIELDS]

    expanded = set(supported)
    for f in list(supported):
        if f == "market_cap":
            expanded |= {"price", "diluted_shares"}

    by_source: dict = {}
    for field in expanded:
        for src in ROUTING.get(field, []):
            by_source.setdefault(src, []).append(field)

    fetched_per_field: dict[str, list[dict]] = {}
    for src, src_fields in by_source.items():
        try:
            payload, src_errors = src.fetch(ticker, sorted(set(src_fields)))
        except Exception as exc:
            errors.append(f"{src.__name__}: {exc}")
            continue
        for err in src_errors:
            errors.append(err)
        for field, entry in payload.items():
            fetched_per_field.setdefault(field, []).append(entry)

    # Single source: take the only candidate. (verify.merge_sources still handles edge cases.)
    for field in expanded:
        candidates = fetched_per_field.get(field, [])
        if not candidates:
            continue
        merged, warns = verify.merge_sources(field, candidates)
        if merged is not None:
            data[field] = merged
        for w in warns:
            errors.append(w)

    # Derivations for any requested fields still missing.
    for field in supported:
        if field in data:
            continue
        derivation = DERIVATIONS.get(field)
        if derivation:
            _, fn = derivation
            derived = fn(data)
            if derived is not None:
                data[field] = derived

    # Unsupported fields — record one structured error per request, list them in missing.
    for field in fields:
        if field in UNSUPPORTED_FIELDS:
            errors.append(
                f"{field}: field_unsupported_by_fm — financial-manager does not surface this field "
                f"via API-token endpoints; extend FM to expose it"
            )

    for field in fields:
        if field not in data:
            missing.append(field)

    return data, missing, errors


def _build_envelope(ticker: str, data: dict, missing: list[str], errors: list[str], do_verify: bool) -> dict:
    passed: list[str] = []
    failed: list[str] = []
    warnings: list[str] = []

    if do_verify:
        ip, ifail, iwarn = verify.run_identities(data)
        passed += ip
        failed += ifail
        warnings += iwarn
        warnings += verify.check_signs(data)
        fp, fwarn = verify.check_freshness(data)
        passed += fp
        warnings += fwarn

    return {
        "ticker": ticker.upper(),
        "fetched_at": _now_iso(),
        "data": data,
        "verification": {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "confidence": verify.aggregate_confidence(data),
        },
        "missing": missing,
        "errors": errors,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="fetch.py", description="fetch-stock-data internal skill entry point")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--fields", required=True, help="comma-separated field IDs")
    parser.add_argument("--verify", choices=["strict", "loose", "off"], default="strict")
    parser.add_argument("--as-of", default="live")
    parser.add_argument("--format", choices=["json"], default="json")

    args = parser.parse_args(argv)
    ticker = args.ticker.strip().upper()
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    if not fields:
        print(json.dumps({"error": "no fields requested"}), file=sys.stderr)
        return 2

    do_verify = args.verify != "off"
    data, missing, errors = _gather(ticker, fields)
    envelope = _build_envelope(ticker, data, missing, errors, do_verify=do_verify)

    print(json.dumps(envelope, default=str))
    if not missing and not errors:
        return 0
    return 3 if data else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
