"""EOD scanner output assembly (brief Section 38 — the exact minimum column list).

Builds the human-readable scan table from a computed feature frame's LAST row
per symbol. Ranking, when shown, is explicitly RESEARCH_RANK, never
BEST_STOCK/HIGH_PROBABILITY/BUY_SCORE (brief Section 82).
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.strategy.entries import ENTRY_MODEL_COLS
from ema_scanner.strategy.scoring import (
    compute_composite_heuristic_score,
    compute_score_components,
    generate_signal_reason,
)

SCANNER_COLUMNS = [
    "Symbol", "Company", "Analysis_Date", "Signal_State", "Daily_EMA10", "Daily_EMA20", "Daily_EMA89", "Daily_EMA200",
    "Daily_Alignment", "Weekly_EMA10", "Weekly_EMA20", "Weekly_EMA89", "Weekly_EMA200", "Weekly_Alignment",
    "MTF_State", "Cluster_Width_Pct", "Cluster_Expansion_State", "EMA20_Slope_Pct_10D", "ATR14", "ATR_Pct",
    "RS_20D", "RS_60D", "RS_120D", "RS_Percentile", "Market_Regime", "Pullback_State",
    "Confirmed_Swing_High", "Confirmed_Swing_Low", "Entry_Models_Triggered", "Suggested_Entry_Reference",
    "Suggested_Stop", "Stop_Distance_Pct", "Data_Quality", "Research_Rank_Score", "Signal_Reason",
]


def build_scanner_row(symbol: str, company: str | None, feats: pd.DataFrame, data_quality_status: str) -> dict:
    row = feats.iloc[-1]
    triggered = [label for col, label in ENTRY_MODEL_COLS.items() if bool(row.get(col, False))]
    scores = compute_score_components(row)
    heuristic = compute_composite_heuristic_score(scores)
    return {
        "Symbol": symbol, "Company": company, "Analysis_Date": feats.index[-1],
        "Signal_State": row.get("Signal_State"),
        "Daily_EMA10": row.get("EMA10"), "Daily_EMA20": row.get("EMA20"), "Daily_EMA89": row.get("EMA89"), "Daily_EMA200": row.get("EMA200"),
        "Daily_Alignment": row.get("Daily_State"),
        "Weekly_EMA10": row.get("EMA10_W"), "Weekly_EMA20": row.get("EMA20_W"), "Weekly_EMA89": row.get("EMA89_W"), "Weekly_EMA200": row.get("EMA200_W"),
        "Weekly_Alignment": row.get("Weekly_State"), "MTF_State": row.get("MTF_State"),
        "Cluster_Width_Pct": row.get("Cluster_Width_Pct"), "Cluster_Expansion_State": row.get("Cluster_Expansion_State"),
        "EMA20_Slope_Pct_10D": row.get("EMA20_Slope_Pct_10D"), "ATR14": row.get("ATR14"), "ATR_Pct": row.get("ATR_Pct"),
        "RS_20D": row.get("RS_20D"), "RS_60D": row.get("RS_60D"), "RS_120D": row.get("RS_120D"), "RS_Percentile": None,
        "Market_Regime": row.get("Market_Regime"), "Pullback_State": row.get("Pullback_State"),
        "Confirmed_Swing_High": row.get("Swing_High_Stop"), "Confirmed_Swing_Low": row.get("Swing_Low_Stop"),
        "Entry_Models_Triggered": ", ".join(triggered) if triggered else None,
        "Suggested_Entry_Reference": row.get("Close"), "Suggested_Stop": row.get("Swing_Low_Stop"),
        "Stop_Distance_Pct": row.get("Stop_Distance_Pct_Long"), "Data_Quality": data_quality_status,
        "Research_Rank_Score": heuristic,  # explicitly a HEURISTIC_RESEARCH_SCORE, see scoring.py
        "Signal_Reason": generate_signal_reason(row),
    }


def build_scanner_table(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=SCANNER_COLUMNS)
    if not df.empty:
        df = df.sort_values("Research_Rank_Score", ascending=False, na_position="last").reset_index(drop=True)
        df.insert(0, "Rank_ID", range(1, len(df) + 1))
    return df
