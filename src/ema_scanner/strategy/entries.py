"""Entry models A-E (notebook Cell 28; audit row 24).

Five INDEPENDENTLY identified, separately-tested long-side entry definitions
(reverse logic applies conceptually for short-side research, per the source
note's point 8 — not implemented here, since the notebook itself never
implements the short side either; see STRATEGY_SPEC.md). None is combined into
one opaque signal (brief Section 7): each is its own boolean column, and the
scanner shows exactly which model(s) triggered.
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.features.alignment import STATE_BEARISH_ALIGNED, STATE_BULLISH_ALIGNED
from ema_scanner.features.swing import vectorized_last_confirmed_swing_high


def entry_model_A_fresh_alignment(state: pd.Series) -> pd.Series:
    prev = state.shift(1)
    return ((prev != STATE_BULLISH_ALIGNED) & (state == STATE_BULLISH_ALIGNED)).fillna(False).rename(
        "EntryA_FreshAlignment"
    )


def entry_model_B_cluster_breakout(price: pd.Series, cluster_max: pd.Series) -> pd.Series:
    cond = (price.shift(1) <= cluster_max.shift(1)) & (price > cluster_max)
    return cond.fillna(False).rename("EntryB_ClusterBreakout")


def entry_model_C_pullback_continuation(pullback_state: pd.Series, price: pd.Series, ema20: pd.Series) -> pd.Series:
    was_pulling_back = pullback_state.shift(1).isin(["SHALLOW_PULLBACK", "MODERATE_PULLBACK"])
    reclaims = (price.shift(1) <= ema20.shift(1)) & (price > ema20)
    return (was_pulling_back & reclaims).fillna(False).rename("EntryC_PullbackContinuation")


def entry_model_D_swing_high_breakout(price: pd.Series, state: pd.Series, last_confirmed_swing_high: pd.Series) -> pd.Series:
    cond = (
        (price.shift(1) <= last_confirmed_swing_high.shift(1))
        & (price > last_confirmed_swing_high)
        & (state == STATE_BULLISH_ALIGNED)
    )
    return cond.fillna(False).rename("EntryD_SwingHighBreakout")


def entry_model_E_reclaim_after_pullback(
    pullback_state: pd.Series, price: pd.Series, cluster_center: pd.Series, state: pd.Series
) -> pd.Series:
    was_pulling_back = pullback_state.shift(1).isin(["SHALLOW_PULLBACK", "MODERATE_PULLBACK", "DEEP_PULLBACK"])
    reclaims_center = (price.shift(1) <= cluster_center.shift(1)) & (price > cluster_center)
    structure_intact = state != STATE_BEARISH_ALIGNED
    return (was_pulling_back & reclaims_center & structure_intact).fillna(False).rename("EntryE_ReclaimAfterPullback")


ENTRY_MODEL_COLS = {
    "EntryA_FreshAlignment": "Immediate crossover / fresh alignment",
    "EntryB_ClusterBreakout": "Price-through-cluster breakout",
    "EntryC_PullbackContinuation": "Pullback continuation",
    "EntryD_SwingHighBreakout": "Swing-high breakout",
    "EntryE_ReclaimAfterPullback": "Reclaim after pullback",
}


def compute_all_entry_models(
    df: pd.DataFrame, swing_df: pd.DataFrame, state: pd.Series, pullback_state: pd.Series,
    suffix: str = "", enabled: tuple[str, ...] = ("A", "B", "C", "D", "E"),
) -> pd.DataFrame:
    out = df.copy()
    price = out["Close"]
    cluster_cols = [f"EMA10{suffix}", f"EMA20{suffix}", f"EMA89{suffix}", f"EMA200{suffix}"]
    cluster_max = out[cluster_cols].max(axis=1)
    last_swing_high = vectorized_last_confirmed_swing_high(swing_df)

    if "A" in enabled:
        out["EntryA_FreshAlignment"] = entry_model_A_fresh_alignment(state)
    if "B" in enabled:
        out["EntryB_ClusterBreakout"] = entry_model_B_cluster_breakout(price, cluster_max)
    if "C" in enabled:
        out["EntryC_PullbackContinuation"] = entry_model_C_pullback_continuation(pullback_state, price, out[f"EMA20{suffix}"])
    if "D" in enabled:
        out["EntryD_SwingHighBreakout"] = entry_model_D_swing_high_breakout(price, state, last_swing_high)
    if "E" in enabled:
        out["EntryE_ReclaimAfterPullback"] = entry_model_E_reclaim_after_pullback(
            pullback_state, price, out[f"Cluster_Center{suffix}"], state
        )
    return out
