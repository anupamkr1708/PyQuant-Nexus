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


def compute_universe_rs_percentile(
    feature_frames: dict[str, pd.DataFrame], analysis_date, rs_col: str = "RS_60D",
) -> pd.Series:
    """Phase-2 Section 10 -- BLOCKER fix: v1's scanner exposed an
    "RS Percentile" column but never actually computed it (always None). This
    is the universe-level cross-sectional stage the brief requires:

        per-symbol features -> assemble same-date universe -> cross-sectional
        percentile -> inject back into candidate records

    Uses ONLY the values at `analysis_date` (a single point-in-time cross-
    section across the ELIGIBLE universe) -- never a different date per
    symbol and never a future date, so this cannot leak information. A
    symbol missing `rs_col` at `analysis_date` (e.g. insufficient history, or
    not in the eligible universe that day) is simply excluded from the
    ranking, not given a fabricated percentile.
    """
    values = {}
    for symbol, feats in feature_frames.items():
        if analysis_date in feats.index and rs_col in feats.columns:
            v = feats.loc[analysis_date, rs_col]
            if pd.notna(v):
                values[symbol] = v
    if not values:
        return pd.Series(dtype=float)
    same_date_cross_section = pd.Series(values)
    return cross_sectional_percentile(same_date_cross_section)
