"""Heuristic research score (notebook Cell 36; audit row 28).

CRITICAL (brief Section 8): this score is a DIAGNOSTIC / RESEARCH RANKING TOOL
ONLY. It is never the trading decision, never called "probability", "confidence",
or "expected return" anywhere in this codebase. Production signal triggers come
from strategy/entries.py's explicit boolean rules, not from this score. If you
are about to sort/filter tradable signals by this score, stop — see
research/statistics.py for what would actually be required to call something a
statistically validated ranking (brief Section 82).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_score_components(row: pd.Series) -> dict:
    scores = {}
    scores["Trend_Alignment_Score"] = (
        1.0 if row.get("Daily_State") == "BULLISH_ALIGNED"
        else (0.5 if row.get("Daily_State") == "MIXED" else 0.0)
    )
    mtf = str(row.get("MTF_State", ""))
    scores["MultiTimeframe_Score"] = 1.0 if mtf.startswith("FULL_TREND_ALIGNMENT") else (0.5 if "PULLBACK" in mtf else 0.0)
    exp_state = row.get("Cluster_Expansion_State")
    scores["Cluster_Expansion_Score"] = 1.0 if exp_state == "EXPANDING" else (0.5 if exp_state == "FLAT" else 0.0)
    slope = row.get("EMA20_Slope_Pct_10D", np.nan)
    scores["Momentum_Score"] = float(np.clip((slope + 5) / 10, 0, 1)) if pd.notna(slope) else np.nan
    rs = row.get("RS_60D", np.nan)
    scores["RelativeStrength_Score"] = float(np.clip((rs + 10) / 20, 0, 1)) if pd.notna(rs) else np.nan
    turnover_ratio = row.get("Volume_Ratio", np.nan)
    scores["Liquidity_Score"] = float(np.clip(turnover_ratio, 0, 2) / 2) if pd.notna(turnover_ratio) else np.nan
    pb = row.get("Pullback_State")
    scores["Pullback_Quality_Score"] = 1.0 if pb == "SHALLOW_PULLBACK" else (0.6 if pb == "MODERATE_PULLBACK" else (0.2 if pb == "DEEP_PULLBACK" else 0.0))
    return scores


def compute_composite_heuristic_score(scores: dict, weights: dict | None = None) -> float:
    """EXPLICITLY a heuristic. See module docstring."""
    if weights is None:
        weights = {k: 1.0 / len(scores) for k in scores}
    vals = [(scores[k] * weights.get(k, 0)) for k in scores if pd.notna(scores[k])]
    wsum = sum(weights.get(k, 0) for k in scores if pd.notna(scores[k]))
    return float(sum(vals) / wsum) if wsum else np.nan


def generate_signal_reason(row: pd.Series) -> str:
    """Deterministic, rule-derived text. NEVER uses "high probability", "strong
    chance", "AI believes", or similar unsupported language (brief Section 37) —
    every clause below is a direct read of a computed column, nothing inferred."""
    parts = []
    if row.get("Daily_State") == "BULLISH_ALIGNED":
        parts.append("Daily EMA structure is bullish (EMA10>EMA20>EMA89>EMA200).")
    elif row.get("Daily_State") == "BEARISH_ALIGNED":
        parts.append("Daily EMA structure is bearish (EMA10<EMA20<EMA89<EMA200).")
    else:
        parts.append("Daily EMA structure is mixed / not fully aligned.")
    if row.get("Weekly_State") == "BULLISH_ALIGNED":
        parts.append("Weekly EMA structure is also bullish.")
    elif row.get("Weekly_State") == "BEARISH_ALIGNED":
        parts.append("Weekly EMA structure is bearish.")
    exp_state = row.get("Cluster_Expansion_State")
    if exp_state == "EXPANDING":
        parts.append("EMA cluster width is expanding.")
    elif exp_state == "CONTRACTING":
        parts.append("EMA cluster is compressing.")
    if row.get("Price_vs_EMA200") is True:
        parts.append("Price is above EMA200.")
    elif row.get("Price_vs_EMA200") is False:
        parts.append("Price is below EMA200.")
    rs = row.get("RS_60D")
    if pd.notna(rs):
        parts.append(f"60-day relative strength vs index is {'positive' if rs > 0 else 'negative'} ({rs:.1f}%).")
    pb = row.get("Pullback_State")
    if pb in ("SHALLOW_PULLBACK", "MODERATE_PULLBACK"):
        parts.append(f"Stock is in a {pb.replace('_', ' ').lower()} toward the EMA cluster.")
    if row.get("EntryD_SwingHighBreakout"):
        parts.append("A confirmed break of the most recent swing high has occurred.")
    return " ".join(parts) if parts else "Insufficient data to generate a reason."
