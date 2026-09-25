"""EMA cluster engine + crossover Definitions A-D (notebook Cell 20; audit rows 19-20).

RESEARCH HYPOTHESIS: compression/expansion use ROLLING PERCENTILE thresholds (not
a fixed universal number), because volatility differs across stocks. Definitions
A-D are four INDEPENDENT, separately testable interpretations of "EMA cluster
crossover" from the source note (which does not give one precise definition) —
none is asserted correct, and none is merged into the others (brief Section 6).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ema_scanner.features.alignment import STATE_BULLISH_ALIGNED


def compute_cluster_metrics(df: pd.DataFrame, close_col: str = "Close", suffix: str = "") -> pd.DataFrame:
    out = df.copy()
    e10, e20, e89, e200 = (
        out[f"EMA10{suffix}"], out[f"EMA20{suffix}"], out[f"EMA89{suffix}"], out[f"EMA200{suffix}"]
    )
    stacked = pd.concat([e10, e20, e89, e200], axis=1)
    cmax, cmin = stacked.max(axis=1), stacked.min(axis=1)
    out[f"Cluster_Width_Pct{suffix}"] = (cmax - cmin) / out[close_col] * 100.0
    out[f"Cluster_Center{suffix}"] = stacked.mean(axis=1)
    out[f"Cluster_Max{suffix}"] = cmax
    out[f"Cluster_Min{suffix}"] = cmin
    for a, b in [("EMA10", "EMA20"), ("EMA20", "EMA89"), ("EMA89", "EMA200"), ("EMA10", "EMA200")]:
        av, bv = out[f"{a}{suffix}"], out[f"{b}{suffix}"]
        out[f"Dist_{a}_{b}_Pct{suffix}"] = (av - bv) / out[close_col] * 100.0
    return out


def compute_cluster_compression(
    df: pd.DataFrame, suffix: str = "", lookback: int = 252,
    compression_pctl: float = 0.20, expansion_pctl: float = 0.80,
) -> pd.DataFrame:
    out = df.copy()
    width = out[f"Cluster_Width_Pct{suffix}"]
    pctl_rank = width.rolling(lookback, min_periods=30).apply(lambda w: (w[-1] <= w).mean(), raw=True)
    out[f"Cluster_Width_Percentile{suffix}"] = pctl_rank
    out[f"Cluster_Compressed_Flag{suffix}"] = pctl_rank <= compression_pctl
    out[f"Cluster_ExpandedRegime_Flag{suffix}"] = pctl_rank >= expansion_pctl
    return out


def compute_cluster_expansion(
    df: pd.DataFrame, suffix: str = "", lookback: int = 252, flat_band_pctl: float = 0.10,
) -> pd.DataFrame:
    out = df.copy()
    width = out[f"Cluster_Width_Pct{suffix}"]
    out[f"Cluster_Width_Change_1D{suffix}"] = width.diff(1)
    out[f"Cluster_Width_Change_5D{suffix}"] = width.diff(5)

    def _slope(y):
        if np.isnan(y).any():
            return np.nan
        return np.polyfit(np.arange(len(y)), y, 1)[0]

    out[f"Cluster_Width_Slope{suffix}"] = width.rolling(5).apply(_slope, raw=True)
    change5 = out[f"Cluster_Width_Change_5D{suffix}"]
    roll = change5.rolling(lookback, min_periods=30)
    lo, hi = roll.quantile(0.5 - flat_band_pctl / 2), roll.quantile(0.5 + flat_band_pctl / 2)
    state = pd.Series("FLAT", index=out.index)
    state[change5 > hi] = "EXPANDING"
    state[change5 < lo] = "CONTRACTING"
    state[change5.isna() | lo.isna() | hi.isna()] = np.nan
    out[f"Cluster_Expansion_State{suffix}"] = state
    return out


def definition_A_sequential_crossover(df: pd.DataFrame, suffix: str = "", max_gap: int = 10) -> pd.Series:
    """DEF A: EMA10xEMA20 -> EMA20xEMA89 -> EMA89xEMA200, each within max_gap sessions."""
    x1, x2, x3 = (
        df[f"BULL_X_EMA10_EMA20{suffix}"], df[f"BULL_X_EMA20_EMA89{suffix}"], df[f"BULL_X_EMA89_EMA200{suffix}"]
    )
    idx = df.index
    result = np.zeros(len(idx), dtype=bool)
    i1s, i2s, i3s = np.where(x1.to_numpy())[0], np.where(x2.to_numpy())[0], np.where(x3.to_numpy())[0]
    for i3 in i3s:
        cand2 = [i for i in i2s if 0 <= i3 - i <= max_gap]
        for i2 in cand2:
            if any(0 <= i2 - i1 <= max_gap for i1 in i1s):
                result[i3] = True
                break
    return pd.Series(result, index=idx, name=f"DefA_SequentialCrossover{suffix}")


def definition_B_alignment_transition(state: pd.Series) -> pd.Series:
    """DEF B: previous state != bullish, current state == bullish."""
    prev = state.shift(1)
    return (
        (prev != STATE_BULLISH_ALIGNED) & (state == STATE_BULLISH_ALIGNED)
    ).fillna(False).rename("DefB_AlignmentTransition")


def definition_C_price_through_cluster(df: pd.DataFrame, close_col: str = "Close", suffix: str = "") -> pd.Series:
    """DEF C: price was <= cluster max previously, now > all four EMAs."""
    emas = [df[f"EMA10{suffix}"], df[f"EMA20{suffix}"], df[f"EMA89{suffix}"], df[f"EMA200{suffix}"]]
    cluster_max = pd.concat(emas, axis=1).max(axis=1)
    price = df[close_col]
    prev_below = price.shift(1) <= cluster_max.shift(1)
    now_above_all = np.logical_and.reduce([price > e for e in emas])
    return (prev_below & now_above_all).fillna(False).rename(f"DefC_PriceThroughCluster{suffix}")


def definition_D_compression_then_expansion(df: pd.DataFrame, suffix: str = "", lookahead: int = 10) -> pd.Series:
    """DEF D: cluster was compressed recently AND is now EXPANDING with a bullish directional bias."""
    compressed_recently = df[f"Cluster_Compressed_Flag{suffix}"].rolling(lookahead, min_periods=1).max().astype(bool)
    expanding_now = df[f"Cluster_Expansion_State{suffix}"] == "EXPANDING"
    directional_bull = df["Close"] > df[f"Cluster_Center{suffix}"]
    compressed_prev = compressed_recently.shift(1, fill_value=False)
    cond = compressed_prev & expanding_now.fillna(False) & directional_bull.fillna(False)
    return cond.fillna(False).rename(f"DefD_CompressionExpansion{suffix}")
