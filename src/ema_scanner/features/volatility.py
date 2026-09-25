"""Slope and ATR/volatility engine (notebook Cell 22; audit row 21).

ATR: MATHEMATICAL DEFINITION, preserved exactly.
    TR = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
    ATR = Wilder-style EWM of TR: alpha=1/period, adjust=False, min_periods=period

Slope: a K-session percentage change of an EMA, explicitly NOT called
"annualized" (brief Section 28 — precise naming only).
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.features.ema import EMA_ROLE_NAMES


def compute_ema_slopes(df: pd.DataFrame, suffix: str = "", k: int = 10) -> pd.DataFrame:
    out = df.copy()
    for name in EMA_ROLE_NAMES:
        col = f"{name}{suffix}"
        out[f"{name}_Slope_Pct_{k}D{suffix}"] = (out[col] / out[col].shift(k) - 1.0) * 100.0
        out[f"{name}_Slope_PerDay{suffix}"] = out[f"{name}_Slope_Pct_{k}D{suffix}"] / k
    return out


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    high, low, close_prev = out["High"], out["Low"], out["Close"].shift(1)
    tr = pd.concat(
        [(high - low), (high - close_prev).abs(), (low - close_prev).abs()], axis=1
    ).max(axis=1)
    out[f"ATR{period}"] = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    out["ATR_Pct"] = out[f"ATR{period}"] / out["Close"] * 100.0
    for name in EMA_ROLE_NAMES:
        if name in out.columns:
            out[f"Distance_to_{name}_ATR"] = (out["Close"] - out[name]) / out[f"ATR{period}"]
    return out
