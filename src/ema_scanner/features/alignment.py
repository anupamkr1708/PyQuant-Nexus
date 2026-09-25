"""EMA alignment classification (notebook Cell 18; audit row 18).

MATHEMATICAL DEFINITION, preserved exactly — strict inequalities, no rounding:

    BULLISH_ALIGNED: EMA10 > EMA20 > EMA89 > EMA200
    BEARISH_ALIGNED: EMA10 < EMA20 < EMA89 < EMA200
    otherwise:       MIXED

Do not replace strict `>`/`<` with `>=`/`<=` — the refactor brief is explicit about
this (Section 4).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STATE_BULLISH_ALIGNED = "BULLISH_ALIGNED"
STATE_BEARISH_ALIGNED = "BEARISH_ALIGNED"
STATE_MIXED = "MIXED"


def classify_alignment(e10: pd.Series, e20: pd.Series, e89: pd.Series, e200: pd.Series) -> pd.Series:
    bullish = (e10 > e20) & (e20 > e89) & (e89 > e200)
    bearish = (e10 < e20) & (e20 < e89) & (e89 < e200)
    state = pd.Series(STATE_MIXED, index=e10.index)
    state[bullish] = STATE_BULLISH_ALIGNED
    state[bearish] = STATE_BEARISH_ALIGNED
    has_nan = e10.isna() | e20.isna() | e89.isna() | e200.isna()
    state[has_nan] = np.nan
    return state


# Daily-vs-Weekly multi-timeframe agreement matrix (Section 12 of the brief):
# reported for diagnostics, never auto-filtered.
MTF_LABELS = {
    (STATE_BULLISH_ALIGNED, STATE_BULLISH_ALIGNED): "FULL_TREND_ALIGNMENT_BULL",
    (STATE_BULLISH_ALIGNED, STATE_MIXED): "WEEKLY_BULL_DAILY_PULLBACK",
    (STATE_BULLISH_ALIGNED, STATE_BEARISH_ALIGNED): "WEEKLY_BULL_DAILY_BEAR_COUNTERTREND",
    (STATE_BEARISH_ALIGNED, STATE_BEARISH_ALIGNED): "FULL_BEAR_ALIGNMENT",
    (STATE_BEARISH_ALIGNED, STATE_MIXED): "WEEKLY_BEAR_DAILY_PULLBACK",
    (STATE_BEARISH_ALIGNED, STATE_BULLISH_ALIGNED): "WEEKLY_BEAR_DAILY_BULL_COUNTERTREND",
    (STATE_MIXED, STATE_BULLISH_ALIGNED): "WEEKLY_MIXED_DAILY_BULL",
    (STATE_MIXED, STATE_BEARISH_ALIGNED): "WEEKLY_MIXED_DAILY_BEAR",
    (STATE_MIXED, STATE_MIXED): "WEEKLY_MIXED_DAILY_MIXED",
}


def compute_mtf_matrix(weekly_state: pd.Series, daily_state: pd.Series) -> pd.Series:
    pairs = list(zip(weekly_state, daily_state))
    labels = [MTF_LABELS.get(p, np.nan) for p in pairs]
    return pd.Series(labels, index=daily_state.index, name="MTF_State")
