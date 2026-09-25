"""Swing structure engine (notebook Cell 24; audit row 22).

CRITICAL no-look-ahead rule, preserved exactly: a fractal pivot at bar t (left/right
window) is only CONFIRMED `right` bars later. All downstream consumers must use the
confirmation date, never the swing date itself, as the information-availability
date (brief Section 31). See tests/lookahead/test_swing_no_lookahead.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_swing_points(
    df: pd.DataFrame, left: int = 5, right: int = 5, low_col: str = "Low", high_col: str = "High"
) -> pd.DataFrame:
    lows, highs = df[low_col].to_numpy(dtype=float), df[high_col].to_numpy(dtype=float)
    n, idx = len(df), df.index
    is_swing_low, is_swing_high = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)

    for t in range(left, n - right):
        wl = lows[t - left : t + right + 1]
        if lows[t] == wl.min() and np.sum(wl == wl.min()) == 1:
            is_swing_low[t] = True
        wh = highs[t - left : t + right + 1]
        if highs[t] == wh.max() and np.sum(wh == wh.max()) == 1:
            is_swing_high[t] = True

    out = df.copy()
    out["Is_Swing_Low"], out["Is_Swing_High"] = is_swing_low, is_swing_high
    confirmed_idx = np.minimum(np.arange(n) + right, n - 1)
    out["Swing_Low_Confirmed_At"] = idx[confirmed_idx]
    out["Swing_High_Confirmed_At"] = idx[confirmed_idx]
    not_confirmable = np.arange(n) > (n - 1 - right)
    out.loc[not_confirmable, "Is_Swing_Low"] = False
    out.loc[not_confirmable, "Is_Swing_High"] = False
    return out


def latest_confirmed_swing_low(swing_df: pd.DataFrame, as_of_date, low_col: str = "Low") -> dict:
    mask = (
        swing_df["Is_Swing_Low"]
        & (swing_df["Swing_Low_Confirmed_At"] <= as_of_date)
        & (swing_df.index <= as_of_date)
    )
    eligible = swing_df[mask]
    if eligible.empty:
        return {"date": None, "price": None}
    last_date = eligible.index[-1]
    return {"date": last_date, "price": float(eligible.loc[last_date, low_col])}


def latest_confirmed_swing_high(swing_df: pd.DataFrame, as_of_date, high_col: str = "High") -> dict:
    mask = (
        swing_df["Is_Swing_High"]
        & (swing_df["Swing_High_Confirmed_At"] <= as_of_date)
        & (swing_df.index <= as_of_date)
    )
    eligible = swing_df[mask]
    if eligible.empty:
        return {"date": None, "price": None}
    last_date = eligible.index[-1]
    return {"date": last_date, "price": float(eligible.loc[last_date, high_col])}


def vectorized_last_confirmed_swing_low(swing_df: pd.DataFrame, low_col: str = "Low") -> pd.Series:
    """Places each swing-low PRICE at its CONFIRMATION date (not the swing date), then
    forward-fills — the vectorized form of latest_confirmed_swing_low."""
    confirmed_value = pd.Series(np.nan, index=swing_df.index)
    for swing_date, row in swing_df[swing_df["Is_Swing_Low"]].iterrows():
        confirmed_value.loc[row["Swing_Low_Confirmed_At"]] = row[low_col]
    return confirmed_value.ffill()


def vectorized_last_confirmed_swing_low_audit(swing_df: pd.DataFrame) -> pd.DataFrame:
    """Phase-2 Section 20: companion audit trail to the price series above --
    for every date, which SWING (its own pivot date) and CONFIRMATION date
    produced the currently-forward-filled stop price. Returned as two
    forward-filled columns so a trade record can cite exactly which swing its
    stop came from (stop_source_swing_date, stop_available_date)."""
    swing_date_col = pd.Series(pd.NaT, index=swing_df.index, dtype="object")
    confirm_date_col = pd.Series(pd.NaT, index=swing_df.index, dtype="object")
    for swing_date, row in swing_df[swing_df["Is_Swing_Low"]].iterrows():
        confirm_at = row["Swing_Low_Confirmed_At"]
        swing_date_col.loc[confirm_at] = swing_date
        confirm_date_col.loc[confirm_at] = confirm_at
    # ffill on an all-object (pd.NaT-seeded) column triggers a pandas
    # FutureWarning about a downcast that does not actually change behavior
    # here (there is nothing numeric to downcast to -- values are Timestamps).
    # Silenced locally and explicitly, rather than globally, so it doesn't mask
    # unrelated warnings elsewhere.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        swing_date_col = swing_date_col.ffill()
        confirm_date_col = confirm_date_col.ffill()
    return pd.DataFrame({
        "Swing_Low_Source_Date": swing_date_col,
        "Swing_Low_Available_Date": confirm_date_col,
    })



def vectorized_last_confirmed_swing_high(swing_df: pd.DataFrame, high_col: str = "High") -> pd.Series:
    confirmed_value = pd.Series(np.nan, index=swing_df.index)
    for swing_date, row in swing_df[swing_df["Is_Swing_High"]].iterrows():
        confirmed_value.loc[row["Swing_High_Confirmed_At"]] = row[high_col]
    return confirmed_value.ffill()
