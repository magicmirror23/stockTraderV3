"""Options-derived features — IV, Greeks, PCR, OI, skew, term structure.

These features require option chain data from the provider.
When option data is unavailable, returns zero-filled defaults.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from app.providers.base import OptionChain

logger = logging.getLogger(__name__)

# Strikes considered ATM are within this % of spot
_ATM_BAND_PCT = 0.02
# OTM wing boundaries (fraction of spot from ATM)
_OTM_INNER = 0.03
_OTM_OUTER = 0.10


def compute_options_features(chain: OptionChain | None) -> dict[str, float]:
    """Extract features from a single option chain snapshot.

    Returns a flat dict of feature names -> values.
    """
    if chain is None or not chain.rows:
        return _empty_options_features()

    rows = chain.rows
    spot = chain.underlying_price
    if spot <= 0:
        return _empty_options_features()

    calls = [r for r in rows if r.option_type == "CE"]
    puts = [r for r in rows if r.option_type == "PE"]

    features: dict[str, float] = {}

    # ── Put-Call Ratios ──────────────────────────────────────────────
    total_call_oi = sum(r.open_interest for r in calls)
    total_put_oi = sum(r.open_interest for r in puts)
    features["pcr_oi"] = total_put_oi / max(total_call_oi, 1)

    total_call_vol = sum(r.volume for r in calls)
    total_put_vol = sum(r.volume for r in puts)
    features["pcr_volume"] = total_put_vol / max(total_call_vol, 1)

    # Normalised PCR (z-score around historical mean ~1.0)
    features["pcr_oi_zscore"] = (features["pcr_oi"] - 1.0) / 0.35 if features["pcr_oi"] else 0.0

    # ── ATM Implied Volatility ───────────────────────────────────────
    atm_call = _nearest_strike(calls, spot)
    atm_put = _nearest_strike(puts, spot)
    features["atm_iv_call"] = atm_call.iv if atm_call and atm_call.iv else 0.0
    features["atm_iv_put"] = atm_put.iv if atm_put and atm_put.iv else 0.0
    features["atm_iv_avg"] = (features["atm_iv_call"] + features["atm_iv_put"]) / 2

    # ── IV Skew (OTM put avg IV - OTM call avg IV) ──────────────────
    otm_puts = [r for r in puts if spot * (1 - _OTM_OUTER) < r.strike < spot * (1 - _OTM_INNER) and r.iv]
    otm_calls = [r for r in calls if spot * (1 + _OTM_INNER) < r.strike < spot * (1 + _OTM_OUTER) and r.iv]
    avg_otm_put_iv = float(np.mean([r.iv for r in otm_puts])) if otm_puts else 0.0
    avg_otm_call_iv = float(np.mean([r.iv for r in otm_calls])) if otm_calls else 0.0
    features["iv_skew"] = avg_otm_put_iv - avg_otm_call_iv
    features["iv_skew_ratio"] = avg_otm_put_iv / max(avg_otm_call_iv, 1e-6) if avg_otm_call_iv else 0.0

    # ── IV Term Structure (near vs next expiry if available) ─────────
    expiries = sorted({r.expiry for r in rows if hasattr(r, "expiry") and r.expiry})
    if len(expiries) >= 2:
        near_rows = [r for r in rows if getattr(r, "expiry", None) == expiries[0] and r.iv]
        next_rows = [r for r in rows if getattr(r, "expiry", None) == expiries[1] and r.iv]
        near_iv = float(np.mean([r.iv for r in near_rows])) if near_rows else 0.0
        next_iv = float(np.mean([r.iv for r in next_rows])) if next_rows else 0.0
        features["iv_term_spread"] = next_iv - near_iv
        features["iv_term_ratio"] = near_iv / max(next_iv, 1e-6) if next_iv else 0.0
    else:
        features["iv_term_spread"] = 0.0
        features["iv_term_ratio"] = 0.0

    # ── Max Pain Estimate ────────────────────────────────────────────
    features["max_pain"] = _compute_max_pain(calls, puts, spot)
    features["max_pain_distance"] = (features["max_pain"] - spot) / spot if features["max_pain"] else 0.0

    # ── Max OI Strikes ───────────────────────────────────────────────
    max_call_oi_row = max(calls, key=lambda r: r.open_interest) if calls else None
    max_put_oi_row = max(puts, key=lambda r: r.open_interest) if puts else None
    features["max_call_oi_strike"] = max_call_oi_row.strike if max_call_oi_row else 0.0
    features["max_put_oi_strike"] = max_put_oi_row.strike if max_put_oi_row else 0.0
    features["max_oi_range"] = features["max_call_oi_strike"] - features["max_put_oi_strike"]
    features["max_oi_range_pct"] = features["max_oi_range"] / spot if spot else 0.0

    # ── Change in OI ─────────────────────────────────────────────────
    features["total_change_in_oi_calls"] = float(sum(r.change_in_oi for r in calls))
    features["total_change_in_oi_puts"] = float(sum(r.change_in_oi for r in puts))
    features["delta_oi_ratio"] = (
        features["total_change_in_oi_puts"] / max(abs(features["total_change_in_oi_calls"]), 1)
    )

    # ── Aggregate Greeks ─────────────────────────────────────────────
    call_deltas = [r.delta for r in calls if r.delta is not None]
    put_deltas = [r.delta for r in puts if r.delta is not None]
    features["avg_call_delta"] = float(np.mean(call_deltas)) if call_deltas else 0.0
    features["avg_put_delta"] = float(np.mean(put_deltas)) if put_deltas else 0.0
    features["net_delta"] = features["avg_call_delta"] + features["avg_put_delta"]

    call_gammas = [r.gamma for r in calls if r.gamma is not None]
    features["total_gamma"] = float(sum(call_gammas)) if call_gammas else 0.0

    call_vegas = [r.vega for r in calls if getattr(r, "vega", None) is not None]
    put_vegas = [r.vega for r in puts if getattr(r, "vega", None) is not None]
    features["total_vega"] = float(sum(call_vegas) + sum(put_vegas)) if (call_vegas or put_vegas) else 0.0

    # ── IV Percentile Rank (where ATM IV sits vs recent IV range) ────
    # Placeholder: requires historical IV series; set to 0 when unavailable.
    features["iv_percentile_rank"] = 0.0

    return features


def _nearest_strike(options: list, spot: float) -> Any:
    """Return the option row closest to the spot price."""
    if not options:
        return None
    return min(options, key=lambda r: abs(r.strike - spot))


def _compute_max_pain(calls: list, puts: list, spot: float) -> float:
    """Estimate the max-pain strike (strike at which total ITM OI value is minimised).

    Iterates over unique strikes and finds the one that minimises writers' payout.
    """
    all_strikes = sorted({r.strike for r in calls + puts})
    if not all_strikes:
        return 0.0

    min_loss = float("inf")
    max_pain_strike = spot

    for strike in all_strikes:
        loss = 0.0
        for r in calls:
            if r.strike < strike:
                loss += (strike - r.strike) * r.open_interest
        for r in puts:
            if r.strike > strike:
                loss += (r.strike - strike) * r.open_interest
        if loss < min_loss:
            min_loss = loss
            max_pain_strike = strike

    return float(max_pain_strike)


def _empty_options_features() -> dict[str, float]:
    """Return zero-filled options feature dict."""
    keys = [
        "pcr_oi", "pcr_volume", "pcr_oi_zscore",
        "atm_iv_call", "atm_iv_put", "atm_iv_avg",
        "iv_skew", "iv_skew_ratio",
        "iv_term_spread", "iv_term_ratio",
        "max_pain", "max_pain_distance",
        "max_call_oi_strike", "max_put_oi_strike", "max_oi_range", "max_oi_range_pct",
        "total_change_in_oi_calls", "total_change_in_oi_puts", "delta_oi_ratio",
        "avg_call_delta", "avg_put_delta", "net_delta",
        "total_gamma", "total_vega",
        "iv_percentile_rank",
    ]
    return {k: 0.0 for k in keys}


def options_features_to_series(chain: OptionChain | None) -> pd.Series:
    """Convenience wrapper returning a pandas Series."""
    return pd.Series(compute_options_features(chain))
