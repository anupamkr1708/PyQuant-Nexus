"""Pullback / continuation engine (notebook Cell 26; audit rows 23).

RESEARCH HYPOTHESIS: pullback depth = ATR-normalized distance of price BELOW the
EMA cluster center, conditioned on a prior breakout above the cluster within a
"breakout memory" window. Bands are configurable and must be validated
empirically, not assumed correct (see research/event_study.py, hypothesis H5).

`breakout_memory_bars` (default 60) was an unlabeled magic number in the notebook
(a bare `.rolling(60, ...)`); it is now a named, configurable parameter with an
UNCHANGED default (docs/NOTEBOOK_AUDIT.md §4).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PULLBACK_STATES = ["NO_PULLBACK", "SHALLOW_PULLBACK", "MODERATE_PULLBACK", "DEEP_PULLBACK", "TREND_FAILURE"]


def classify_pullback(
    df: pd.DataFrame,
    atr_col: str = "ATR14",
    suffix: str = "",
    shallow_atr: float = 1.0,
    moderate_atr: float = 2.5,
    deep_atr: float = 4.0,
    breakout_memory_bars: int = 60,
) -> pd.Series:
    center, price, atr, ema200 = (
        df[f"Cluster_Center{suffix}"], df["Close"], df[atr_col], df[f"EMA200{suffix}"]
    )
    was_above_cluster = price.shift(1) > center.shift(1)
    ever_broke_out = was_above_cluster.rolling(breakout_memory_bars, min_periods=1).max().astype(bool)
    dist_below_center_atr = (center - price) / atr

    state = pd.Series("NO_PULLBACK", index=df.index)
    in_pullback = ever_broke_out & (price < center)
    state[in_pullback & (dist_below_center_atr <= shallow_atr)] = "SHALLOW_PULLBACK"
    state[in_pullback & (dist_below_center_atr > shallow_atr) & (dist_below_center_atr <= moderate_atr)] = "MODERATE_PULLBACK"
    state[in_pullback & (dist_below_center_atr > moderate_atr) & (dist_below_center_atr <= deep_atr)] = "DEEP_PULLBACK"
    state[in_pullback & (price < ema200)] = "TREND_FAILURE"
    state[atr.isna() | center.isna()] = np.nan
    return state
