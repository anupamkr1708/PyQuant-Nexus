"""Market regime diagnostic (notebook Cell 30; audit row 25).

OPTIONAL FILTER / diagnostic-first (brief Section 33): regime is reported for
segmentation, never auto-applied as a filter unless explicitly enabled downstream.
Benchmark is configurable (NIFTY50 default, matching the notebook's `^NSEI` choice,
or NIFTY200 / a custom index) — the notebook's own default is NOT silently changed.
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.features.ema import compute_ema


def compute_market_regime(
    index_df: pd.DataFrame, close_col: str = "Close",
    ema_fast: int = 20, ema_medium: int = 50, ema_structural: int = 89, ema_long: int = 200,
) -> pd.DataFrame:
    out = index_df.copy()
    out["Index_EMA20"] = compute_ema(out[close_col], ema_fast)
    out["Index_EMA50"] = compute_ema(out[close_col], ema_medium)
    out["Index_EMA89"] = compute_ema(out[close_col], ema_structural)
    out["Index_EMA200"] = compute_ema(out[close_col], ema_long)
    price = out[close_col]
    bull = (price > out["Index_EMA50"]) & (out["Index_EMA50"] > out["Index_EMA200"])
    bear = (price < out["Index_EMA50"]) & (out["Index_EMA50"] < out["Index_EMA200"])
    regime = pd.Series("NEUTRAL", index=out.index)
    regime[bull], regime[bear] = "BULL", "BEAR"
    regime[out["Index_EMA200"].isna()] = None
    out["Market_Regime"] = regime
    return out[["Market_Regime", "Index_EMA20", "Index_EMA50", "Index_EMA89", "Index_EMA200"]]


def attach_market_regime_asof(stock_df: pd.DataFrame, regime_df: pd.DataFrame) -> pd.Series:
    return regime_df["Market_Regime"].reindex(stock_df.index, method="ffill")
