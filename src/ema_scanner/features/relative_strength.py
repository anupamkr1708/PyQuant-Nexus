"""Relative-strength engine (notebook Cell 32; audit row 26). SOURCE-DERIVED RULE."""
from __future__ import annotations

import pandas as pd


def compute_relative_strength(
    stock_close: pd.Series, index_close_aligned: pd.Series, windows: tuple[int, ...] = (20, 60, 120)
) -> pd.DataFrame:
    out = pd.DataFrame(index=stock_close.index)
    for window in windows:
        stock_ret = stock_close / stock_close.shift(window) - 1.0
        index_ret = index_close_aligned / index_close_aligned.shift(window) - 1.0
        out[f"RS_{window}D"] = (stock_ret - index_ret) * 100.0
    return out


def cross_sectional_percentile(rs_series_today: pd.Series) -> pd.Series:
    """Percentile rank of each stock's RS within the universe on a given day.
    Kept SEPARATE from the raw RS value (brief Section 34: don't combine them into
    an unexplained single factor)."""
    return rs_series_today.rank(pct=True) * 100.0
