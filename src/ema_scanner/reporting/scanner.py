"""EOD scanner output assembly (brief Section 38; Phase-2 Section 18 -- BLOCKER).

**Bugs fixed:**
1. v1 built one table where every successfully-processed stock got a row, and
   the CLI counted `len(table)` as "signals found" -- i.e. `signals_found`
   actually meant "stocks successfully processed", not "stocks with an actual
   entry trigger". Fixed: `build_scanner_tables()` now returns FOUR distinct
   datasets (universe diagnostics / candidates / actual signals / failures),
   and only the ACTUAL_SIGNALS row count may be called `signals_found`.
2. v1 reported `Close` as `Suggested_Entry_Reference` unconditionally, even
   when `execution_model == NEXT_OPEN` -- i.e. it implicitly called today's
   close "the entry price" for a strategy that actually enters tomorrow.
   Fixed: explicit `Signal_Close` / `Execution_Model` / `Next_Session_Date` /
   `Execution_Reference` / `Stop_Reference` columns, with `Execution_Reference`
   only populated once a real next-session bar is resolved (never fabricated
   from a positional fallback -- see execution/execution_models.py).

Ranking, when shown, is explicitly RESEARCH_RANK, never
BEST_STOCK/HIGH_PROBABILITY/BUY_SCORE (brief Section 82).
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.execution.execution_models import resolve_execution_price
from ema_scanner.execution.sizing import validate_risk_geometry
from ema_scanner.strategy.entries import ENTRY_MODEL_COLS
from ema_scanner.strategy.scoring import (
    compute_composite_heuristic_score,
    compute_score_components,
    generate_signal_reason,
)

SCANNER_COLUMNS = [
    "Rank_ID", "Symbol", "Company", "Analysis_Date", "Signal_State", "Daily_EMA10", "Daily_EMA20", "Daily_EMA89", "Daily_EMA200",
    "Daily_Alignment", "Weekly_EMA10", "Weekly_EMA20", "Weekly_EMA89", "Weekly_EMA200", "Weekly_Alignment",
    "MTF_State", "Cluster_Width_Pct", "Cluster_Expansion_State", "EMA20_Slope_Pct_10D", "ATR14", "ATR_Pct",
    "RS_20D", "RS_60D", "RS_120D", "RS_Percentile", "Market_Regime", "Pullback_State",
    "Confirmed_Swing_High", "Confirmed_Swing_Low", "Entry_Models_Triggered",
    "Signal_Close", "Execution_Model", "Next_Session_Date", "Execution_Reference",
    "Stop_Reference", "Stop_Distance_Pct", "Risk_Geometry_Valid",
    "Data_Quality", "Eligible_For_Signal", "Research_Rank_Score", "Signal_Reason",
]


def build_scanner_row(
    symbol: str, company: str | None, feats: pd.DataFrame, data_quality_status: str,
    calendar: NSECalendar, execution_model: Literal["same_close", "next_open", "next_close"], eligible_for_signal: bool,
) -> dict:
    row = feats.iloc[-1]
    analysis_date = feats.index[-1]
    triggered = [label for col, label in ENTRY_MODEL_COLS.items() if bool(row.get(col, False))]
    scores = compute_score_components(row)
    heuristic = compute_composite_heuristic_score(scores)

    signal_close = float(row.get("Close")) if pd.notna(row.get("Close")) else None
    stop_ref = row.get("Swing_Low_Stop")
    stop_ref = float(stop_ref) if pd.notna(stop_ref) else None
    risk_geometry_valid = validate_risk_geometry(signal_close, stop_ref, "LONG") if (signal_close is not None and stop_ref is not None) else None

    exe = resolve_execution_price(feats, analysis_date, calendar, execution_model=execution_model)
    # Phase-3 BLOCKER 14 fix: Next_Session_Date is a pure CALENDAR fact --
    # resolvable without needing tomorrow's price to exist at all (this is
    # exactly what a live EOD scan needs: it knows what the next session's
    # DATE will be, even though that session hasn't happened yet and so has
    # no price data). Execution_Reference genuinely requires a future bar to
    # exist (true for historical backtests where "the future" is already in
    # the data; false for a live scan of the latest completed session) and
    # is kept separately gated on that. Setting BOTH to None whenever the
    # price isn't available (the v1/Phase-2 behavior) incorrectly implied
    # the next session's DATE was also unknown.
    if execution_model == "same_close":
        next_session_date = analysis_date
    else:
        next_session_date = calendar.next_session(analysis_date)
    execution_reference = exe.execution_price if exe.status == "OK" else None

    return {
        "Symbol": symbol, "Company": company, "Analysis_Date": analysis_date,
        "Signal_State": row.get("Signal_State"),
        "Daily_EMA10": row.get("EMA10"), "Daily_EMA20": row.get("EMA20"), "Daily_EMA89": row.get("EMA89"), "Daily_EMA200": row.get("EMA200"),
        "Daily_Alignment": row.get("Daily_State"),
        "Weekly_EMA10": row.get("EMA10_W"), "Weekly_EMA20": row.get("EMA20_W"), "Weekly_EMA89": row.get("EMA89_W"), "Weekly_EMA200": row.get("EMA200_W"),
        "Weekly_Alignment": row.get("Weekly_State"), "MTF_State": row.get("MTF_State"),
        "Cluster_Width_Pct": row.get("Cluster_Width_Pct"), "Cluster_Expansion_State": row.get("Cluster_Expansion_State"),
        "EMA20_Slope_Pct_10D": row.get("EMA20_Slope_Pct_10D"), "ATR14": row.get("ATR14"), "ATR_Pct": row.get("ATR_Pct"),
        "RS_20D": row.get("RS_20D"), "RS_60D": row.get("RS_60D"), "RS_120D": row.get("RS_120D"),
        "RS_Percentile": None,  # injected by the caller via features/relative_strength.compute_universe_rs_percentile
        "Market_Regime": row.get("Market_Regime"), "Pullback_State": row.get("Pullback_State"),
        "Confirmed_Swing_High": row.get("Swing_High_Stop"), "Confirmed_Swing_Low": row.get("Swing_Low_Stop"),
        "Entry_Models_Triggered": ", ".join(triggered) if triggered else None,
        # Phase-2 Section 18 fix: Signal_Close is explicitly NOT called "entry
        # price" -- the real (modeled) execution reference is a separate field
        # that respects the configured execution model.
        "Signal_Close": signal_close, "Execution_Model": execution_model,
        "Next_Session_Date": next_session_date, "Execution_Reference": execution_reference,
        "Stop_Reference": stop_ref, "Stop_Distance_Pct": row.get("Stop_Distance_Pct_Long"),
        "Risk_Geometry_Valid": risk_geometry_valid,
        "Data_Quality": data_quality_status, "Eligible_For_Signal": eligible_for_signal,
        "Research_Rank_Score": heuristic,  # explicitly a HEURISTIC_RESEARCH_SCORE, see scoring.py
        "Signal_Reason": generate_signal_reason(row),
        "_has_entry_trigger": bool(triggered),  # internal routing flag, stripped before export
        "_signal_state": row.get("Signal_State"),
    }


def build_scanner_tables(rows: list[dict]) -> dict[str, pd.DataFrame]:
    """Phase-2 Section 18 fix: returns FOUR distinct datasets instead of one
    ambiguous table.

        universe_diagnostics -- every successfully-processed row (full audit trail)
        candidates           -- WATCH/TREND_FORMING/BULLISH_CLUSNTER/PULLBACK,
                                 no entry model actually triggered
        signals               -- rows with >=1 Entry A-E model triggered
                                 (`len(signals)` is the ONLY correct meaning
                                 of "signals_found")
        (failures are tracked separately by the caller -- see models.SymbolFailure)
    """
    if not rows:
        empty = pd.DataFrame(columns=SCANNER_COLUMNS)
        return {"universe_diagnostics": empty, "candidates": empty.copy(), "signals": empty.copy()}

    full = pd.DataFrame(rows)
    has_trigger = full["_has_entry_trigger"]
    export_cols = [c for c in SCANNER_COLUMNS if c != "Rank_ID"]

    def _finalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df[export_cols].copy() if not df.empty else pd.DataFrame(columns=export_cols)
        if not out.empty:
            out = out.sort_values("Research_Rank_Score", ascending=False, na_position="last").reset_index(drop=True)
            out.insert(0, "Rank_ID", range(1, len(out) + 1))
        else:
            out.insert(0, "Rank_ID", [])
        return out

    universe_diagnostics = _finalize(full)
    signals = _finalize(full[has_trigger])
    candidates = _finalize(full[~has_trigger & full["_signal_state"].isin(
        ["WATCH", "TREND_FORMING", "BULLISH_CLUSTER", "PULLBACK"]
    )])
    return {"universe_diagnostics": universe_diagnostics, "candidates": candidates, "signals": signals}


def build_scanner_table(rows: list[dict]) -> pd.DataFrame:
    """Backward-compat shim: returns the universe-diagnostics table (the
    closest analogue to v1's single table). NEW code should call
    `build_scanner_tables` and use `["signals"]` for anything meant to be
    counted as `signals_found`."""
    return build_scanner_tables(rows)["universe_diagnostics"]
