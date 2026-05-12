---
name: fetch-stock-data
description: Internal utility skill that fetches and verifies live stock data (price, TTM financials, balance sheet, multiples, analyst consensus, risk-free rate) from the user's self-hosted financial-manager Next.js API via a bundled Python client. NOT FOR DIRECT USER INVOCATION — called by every data-consuming analysis skill in this plugin (dcf-valuation, fundamental-analysis, stock-eval, stock-valuation, dividend-analysis, short-interest, institutional-ownership, competitor-analysis, insider-trading, technical-analysis) before they begin analysis. Returns compact JSON with accounting-identity checks and freshness validation. Use when an analysis skill needs current, verified market data instead of relying on stale knowledge.
---

# fetch-stock-data — Internal Data Utility

## Purpose

This is an **internal utility skill**. It does not produce investment analysis or signals. It fetches raw stock data from the user's self-hosted `financial-manager` Next.js API,
runs accounting-identity and freshness validation, and returns a single compact JSON envelope for the calling skill to consume.

The skill exists because the plugin's analysis skills (DCF, fundamental, stock-eval, etc.) previously depended on the LLM's knowledge for inputs like price, TTM revenue, FCF, beta,
and net debt. Knowledge cutoffs caused inverted conclusions (e.g., a DCF built on a stale stock price). This skill removes that failure mode by routing every numeric input
through `financial-manager`, which the user controls.

## When to Use

- A caller skill needs current values for any of: price, TTM income/cash-flow/balance-sheet, multiples, beta, analyst consensus, risk-free rate, dividend metrics, ownership,
  short interest.
- The caller passes a `--fields=` list naming exactly the fields it needs (token efficiency).
- Output is JSON only. The caller parses it and proceeds with analysis.

## When NOT to Use

- Do not invoke directly from user prompts. There is no analysis here.
- Do not use to fetch fields not in the catalog below. If a caller needs additional fields, extend `financial-manager` first to surface them via API-token endpoints, then add
  routing in `scripts/sources/fm_src.py`.

## Invocation Contract

```
/us-stock-analysis:fetch-stock-data <TICKER> --fields=<csv> [--verify=strict|loose|off] [--as-of=YYYY-MM-DD]
```

Defaults: `--verify=strict`, `--as-of=live`.

## Field Catalog

| Group | Field IDs |
|---|---|
| Price | `price`, `change`, `change_pct`, `volume`, `52w_high`, `52w_low`, `market_cap` |
| Income (TTM) | `ttm_revenue`, `ttm_gross_profit`, `ttm_op_income`, `ttm_net_income`, `ttm_eps`, `ttm_tax_rate` |
| Cash flow (TTM) | `ttm_fcf`, `ttm_sbc` |
| Balance sheet | `short_term_debt`, `long_term_debt`, `total_debt`, `st_investments`, `total_equity`, `diluted_shares` |
| Margins | `op_margin`, `net_margin`, `fcf_margin` |
| Growth | `rev_cagr_3y`, `rev_cagr_5y`, `rev_cagr_10y`, `eps_cagr_5y` |
| Multiples | `pe_ttm`, `pe_fwd`, `peg` |
| Returns | `roe`, `roa`, `roic` |
| Risk | `beta`, `rf_rate`, `erp` |
| Analyst | `analyst_pt_mean`, `analyst_pt_high`, `analyst_pt_low`, `analyst_count`, `analyst_revenue_2y`, `analyst_eps_2y`, `analyst_rating` |
| Dividends | `div_yield`, `div_payout`, `div_growth_5y` |
| Segments | `segment_revenue` |
| Ownership | `inst_ownership_pct`, `insider_ownership_pct` |
| Short interest | `short_pct_float`, `days_to_cover` |
| **Currently unsupported** (returned in `missing[]`) | `pb`, `ps`, `ev_ebitda`, `ev_fcf`, `ttm_ocf`, `ttm_capex`, `cash`, `net_debt`, `gross_margin` |

The unsupported fields are not exposed by `financial-manager`'s API-token endpoints today. Each request for one returns a structured `field_unsupported_by_fm` error in the
envelope's `errors[]`. Extend `financial-manager` (and then `scripts/sources/fm_src.py`) to add coverage.

## How Claude Should Run This Skill

When invoked with a ticker and `--fields=` list:

1. Resolve the plugin root via the `CLAUDE_PLUGIN_ROOT` environment variable.
2. Execute the bundled fetch script:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/fetch-stock-data/scripts/fetch.py" \
     --ticker <TICKER> \
     --fields <csv> \
     --verify <strict|loose|off> \
     --as-of <YYYY-MM-DD|live> \
     --format json
   ```

3. Return the script's stdout **verbatim** in a single fenced JSON code block. No prose. No tables. No signal block.
4. If the script exits non-zero, return its stderr JSON envelope verbatim — the caller skill needs to see the error structure to handle missing keys, rate limits, or
   unsupported tickers.

## Setup Prerequisites (one-time)

Generate a read-only API token in `financial-manager` (`Bearer fmt_pat_*` format), then export it:

```bash
export FINANCIAL_MANAGER_API_TOKEN=fmt_pat_...
# Optional override; defaults to the deployed Vercel URL below.
export FINANCIAL_MANAGER_BASE_URL=https://financial-manager-borisber87-4227s-projects.vercel.app
```

No Python dependencies are required — the client uses stdlib `urllib`. If the token is missing, the script returns a structured error envelope listing the missing variable.

## Output Format

A single JSON document with this shape (only the requested fields appear in `data`):

```json
{
  "ticker": "INTC",
  "fetched_at": "2026-05-02T15:30:00Z",
  "data": {
    "price":          { "v": 99.62,   "src": "fm",        "ts": "2026-05-02T15:29:50Z", "c": 1.0 },
    "ttm_revenue":    { "v": 54000,   "u": "M_USD", "src": "fm", "ts": "2025", "c": 0.9, "note": "latest annual" },
    "ttm_fcf":        { "v": -3120,   "u": "M_USD", "src": "fm", "ts": "2025", "c": 0.9 },
    "diluted_shares": { "v": 5083,    "u": "M",     "src": "fm", "c": 0.9 },
    "beta":           { "v": 1.35,    "src": "fm",  "c": 0.9 },
    "rf_rate":        { "v": 0.0438,  "src": "fm:fred", "ts": "2026-05-02", "c": 1.0 }
  },
  "verification": {
    "passed":  ["market_cap_identity", "total_debt_identity", "freshness_price"],
    "failed":  [],
    "warnings": [],
    "confidence": 0.94
  },
  "missing": [],
  "errors": []
}
```

Schema: `v`=value, `u`=unit (omitted when implied), `src`=source, `ts`=timestamp, `c`=confidence in `[0,1]`, `note`=derivation/caveat. Units convention: `M_USD` for millions of
USD; rates and margins are decimals (`0.0438` = 4.38%).

## Source

| Source | Role | Auth |
|---|---|---|
| financial-manager (Next.js API) | All catalog fields above | `FINANCIAL_MANAGER_API_TOKEN` (Bearer `fmt_pat_*`) |

Endpoints used: `/api/prices/{ticker}`, `/api/stocks/{ticker}/overview`, `/api/stocks/{ticker}/analyst`, `/api/stocks/{ticker}/segments`, `/api/macro/rates`. All five accept the
read-only API-token model via `getApiAuth`. `financial-manager` itself proxies and caches data from yfinance / FMP / FRED upstream — this skill is a thin client over that
single backend.

## Verification Rules (run when `--verify=strict`)

**Identities** (fail → flagged in `verification.failed`):
- `market_cap == price × diluted_shares` (±5%)
- `total_debt == short_term_debt + long_term_debt` (±2%)
- `fcf_identity` and `net_debt_identity` are skipped automatically when their inputs (`ttm_ocf`, `ttm_capex`, `cash`) are unsupported.

**Sign checks**: any non-negative field (`ttm_revenue`, `total_debt`, `diluted_shares`, etc.) returning a negative value is added to `verification.warnings`.

**Freshness**: `price` ≤24h → `c=1.0`; 24–72h → `c=0.7`, `stale=true`; >72h → `c=0.4`, warning. `financial-manager` caches prices 5min during market hours and 24h after close,
so live calls are typically fresh.

## Convention Note

This skill is the only utility skill in the plugin and does not emit an Investment Signal Block. It is excluded from the signal-block check in `scripts/test-skills.js` and the
prompts-sync check in `scripts/pre-release-check.js`. There is no `prompts/fetch-stock-data.md` because the bundled scripts are Claude-Code-specific and would not work in
Cursor/Gemini/ChatGPT contexts.
