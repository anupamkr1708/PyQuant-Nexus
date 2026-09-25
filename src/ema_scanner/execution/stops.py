"""Stop-loss engine (notebook Cell 34; audit row 27; Phase-2 Section 20 --
swing audit trail added).

SOURCE-DERIVED RULE: stop for a long = the latest CONFIRMED swing low (reverse
for shorts). Preserved exactly, and only usable as of its confirmation date
(features/swing.py enforces that). ATR-based stop is a SEPARATE, OPTIONAL
diagnostic -- never silently substituted for the swing-based stop (brief
Section 27, 42).

Phase-2 addition: `Confirmed_Swing_Low_Date` / `Confirmed_Swing_Low_Available_Date`
columns expose exactly which swing pivot (and its confirmation date) produced
the currently forward-filled `Swing_Low_Stop`, so trade/audit records can cite
it (brief Phase-2 Section 20).
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.features.swing import (
    vectorized_last_confirmed_swing_high,
    vectorized_last_confirmed_swing_low,
    vectorized_last_confirmed_swing_low_audit,
)


def compute_stops(df: pd.DataFrame, swing_df: pd.DataFrame, atr_col: str = "ATR14", atr_stop_multiple: float = 2.5) -> pd.DataFrame:
    out = df.copy()
    out["Swing_Low_Stop"] = vectorized_last_confirmed_swing_low(swing_df)
    out["Swing_High_Stop"] = vectorized_last_confirmed_swing_high(swing_df)

    audit = vectorized_last_confirmed_swing_low_audit(swing_df)
    out["Confirmed_Swing_Low_Date"] = audit["Swing_Low_Source_Date"]
    out["Confirmed_Swing_Low_Available_Date"] = audit["Swing_Low_Available_Date"]

    out["Stop_Distance_Pct_Long"] = (out["Close"] - out["Swing_Low_Stop"]) / out["Close"] * 100.0
    out["Stop_Distance_ATR_Long"] = (out["Close"] - out["Swing_Low_Stop"]) / out[atr_col]
    out["ATR_Based_Stop_Long"] = out["Close"] - atr_stop_multiple * out[atr_col]  # OPTIONAL diagnostic only
    out["Stop_Distance_Pct_Short"] = (out["Swing_High_Stop"] - out["Close"]) / out["Close"] * 100.0
    out["Stop_Distance_ATR_Short"] = (out["Swing_High_Stop"] - out["Close"]) / out[atr_col]
    out["ATR_Based_Stop_Short"] = out["Close"] + atr_stop_multiple * out[atr_col]
    return out
