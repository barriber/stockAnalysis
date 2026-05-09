"""Verification logic for fetch-stock-data: identities, sign checks, freshness."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


# Tolerances for accounting identities (relative).
IDENTITY_TOLERANCES = {
    "fcf_identity":         0.05,
    "net_debt_identity":    0.02,
    "market_cap_identity":  0.05,
    "total_debt_identity":  0.02,
}

# Fields that should always be non-negative.
NON_NEGATIVE_FIELDS = {
    "ttm_revenue", "ttm_gross_profit", "ttm_op_income",
    "ttm_ocf", "ttm_capex", "ttm_sbc",
    "total_debt", "short_term_debt", "long_term_debt",
    "cash", "st_investments", "total_equity",
    "diluted_shares", "market_cap", "volume", "price",
    "analyst_count", "div_yield",
}


def _rel_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def check_identity(name: str, lhs: float, rhs: float, tolerance: float | None = None) -> tuple[bool, float]:
    tol = tolerance if tolerance is not None else IDENTITY_TOLERANCES.get(name, 0.05)
    if not (_is_finite(lhs) and _is_finite(rhs)):
        return False, float("nan")
    diff = _rel_diff(lhs, rhs)
    return diff <= tol, diff


def run_identities(data: dict[str, dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    """Returns (passed, failed, warnings)."""
    passed: list[str] = []
    failed: list[str] = []
    warnings: list[str] = []

    def v(field: str) -> Any:
        entry = data.get(field)
        if entry is None:
            return None
        return entry.get("v")

    pairs = [
        ("fcf_identity",        v("ttm_fcf"),       _safe_sub(v("ttm_ocf"), v("ttm_capex"))),
        ("net_debt_identity",   v("net_debt"),      _safe_sub(v("total_debt"), _safe_add(v("cash"), v("st_investments")))),
        ("market_cap_identity", v("market_cap"),    _safe_mul(v("price"), v("diluted_shares"), 1_000_000)),
        ("total_debt_identity", v("total_debt"),    _safe_add(v("short_term_debt"), v("long_term_debt"))),
    ]

    for name, lhs, rhs in pairs:
        if lhs is None or rhs is None:
            continue
        ok, diff = check_identity(name, lhs, rhs)
        if ok:
            passed.append(name)
        else:
            failed.append(name)
            warnings.append(f"{name} drift {diff:.1%} (lhs={lhs}, rhs={rhs})")

    return passed, failed, warnings


def _safe_add(a: Any, b: Any) -> Any:
    if not (_is_finite(a) and _is_finite(b)):
        return None
    return a + b


def _safe_sub(a: Any, b: Any) -> Any:
    if not (_is_finite(a) and _is_finite(b)):
        return None
    return a - b


def _safe_mul(a: Any, b: Any, scale: float = 1.0) -> Any:
    if not (_is_finite(a) and _is_finite(b)):
        return None
    return a * b * scale


def check_signs(data: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for field in NON_NEGATIVE_FIELDS:
        entry = data.get(field)
        if entry is None:
            continue
        val = entry.get("v")
        if _is_finite(val) and val < 0:
            warnings.append(f"{field} is negative ({val}) — expected non-negative")
    return warnings


def merge_sources(field: str, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
    """Single-source backend: pick the first candidate. Kept for fetch.py interface stability."""
    if not candidates:
        return None, []
    chosen = dict(candidates[0])
    chosen.setdefault("c", 0.9)
    return chosen, []


def check_freshness(data: dict[str, dict[str, Any]], now: datetime | None = None) -> tuple[list[str], list[str]]:
    """Mark stale entries; return (passed, warnings)."""
    now = now or datetime.now(timezone.utc)
    passed: list[str] = []
    warnings: list[str] = []

    price_entry = data.get("price")
    if price_entry and price_entry.get("ts"):
        try:
            ts = datetime.fromisoformat(price_entry["ts"].replace("Z", "+00:00"))
            age_hours = (now - ts).total_seconds() / 3600
            if age_hours <= 24:
                passed.append("freshness_price")
                price_entry.setdefault("c", 1.0)
            elif age_hours <= 72:
                price_entry["c"] = min(price_entry.get("c", 1.0), 0.7)
                price_entry["stale"] = True
                warnings.append(f"price stale ({age_hours:.0f}h)")
            else:
                price_entry["c"] = min(price_entry.get("c", 1.0), 0.4)
                price_entry["stale"] = True
                warnings.append(f"price very stale ({age_hours:.0f}h)")
        except (ValueError, TypeError):
            warnings.append("price timestamp unparseable")

    return passed, warnings


def aggregate_confidence(data: dict[str, dict[str, Any]]) -> float:
    confidences = [
        entry.get("c") for entry in data.values()
        if isinstance(entry, dict) and _is_finite(entry.get("c"))
    ]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 3)
