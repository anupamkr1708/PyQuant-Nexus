"""Liquidity diagnostics (notebook Cell 36 inline block; audit row 28, bug row in §4).

Uses INR terminology ("Average Daily Traded Value") rather than the notebook's
"dollar turnover" naming (brief Section 35) — the underlying numbers are
unchanged, only the label. OPTIONAL FILTER, OFF by default (brief Section 22).
"""
from __future__ import annotations

import pandas as pd


def compute_liquidity_diagnostics(df: pd.DataFrame, volume_window_fast: int = 20, volume_window_slow: int = 50) -> pd.DataFrame:
    out = df.copy()
    out[f"Volume{volume_window_fast}"] = out["Volume"].rolling(volume_window_fast).mean()
    out[f"Volume{volume_window_slow}"] = out["Volume"].rolling(volume_window_slow).mean()
    out["Volume_Ratio"] = out["Volume"] / out[f"Volume{volume_window_fast}"]
    out["Traded_Value"] = out["Close"] * out["Volume"]
    out["Average_Daily_Traded_Value"] = out["Traded_Value"].rolling(volume_window_fast).mean()
    return out


def apply_liquidity_filter(
    df: pd.DataFrame,
    enabled: bool,
    min_price: float = 0.0,
    min_average_daily_traded_value: float = 0.0,
    min_average_volume: float = 0.0,
) -> pd.DataFrame:
    """OPTIONAL FILTER. Returns df unchanged unless explicitly enabled — never
    silently mandatory (brief Section 35)."""
    if not enabled:
        return df
    mask = (
        (df["Close"] >= min_price)
        & (df["Average_Daily_Traded_Value"].fillna(0) >= min_average_daily_traded_value)
        & (df.get("Volume20", pd.Series(0, index=df.index)).fillna(0) >= min_average_volume)
    )
    return df[mask]
