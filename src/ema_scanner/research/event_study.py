"""Historical event study (notebook Cell 38; audit row 30; Phase-3 BLOCKERS 4, 5).

Answers "what happened after these signals?" -- explicitly NOT a tradable
portfolio P&L (brief Section 46). For that, see research/backtest.py, which is a
SEPARATE engine. Do not mix the two outputs into one table.

**Bugs fixed (Phase-3 BLOCKERS 4, 5):** v1 resolved the correct EXECUTION
price via `resolve_execution_price`, but then measured every forward horizon
and MFE/MAE relative to the SIGNAL date's row position, not the EXECUTION
date's. For `next_open`/`next_close`, execution can be one or more sessions
after the signal -- so "Fwd_Ret_1D" was silently measuring 1 session after
the SIGNAL (which could be zero, or even negative, sessions after the actual
entry), not 1 session after the entry actually occurred.

Horizons and MFE/MAE are now anchored on `Execution_Date`'s row position,
with explicit session-stage semantics (module-level `_STAGE_HORIZON_OFFSET`)
matching research/backtest.py's `_EXECUTION_MODEL_TO_STAGE`:

    OPEN stage (next_open):   entry occurs AT that session's Open, so that
        SAME session's Close is a valid "H=1" observation (`fut_loc = loc + h - 1`),
        and that session's own High/Low are valid MFE/MAE observations
        (they occur strictly after the Open entry).
    CLOSE stage (same_close, next_close): entry occurs AT that session's
        Close, so there is no more price path left that session -- "H=1" is
        the FOLLOWING session's close (`fut_loc = loc + h`), and that
        session's own High/Low must be EXCLUDED from MFE/MAE (they occurred
        BEFORE the close-price entry).

Every event record now carries `Signal_Date`, `Execution_Date`,
`Execution_Price`, and `Execution_Model` explicitly (brief Phase-3 Section 4).
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.execution.costs import CostsConfig, compute_round_trip_cost_pct
from ema_scanner.execution.execution_models import resolve_execution_price
from ema_scanner.strategy.entries import ENTRY_MODEL_COLS

FORWARD_HORIZONS = (1, 3, 5, 10, 20, 40)

ExecutionModel = Literal["same_close", "next_open", "next_close"]
EntryStage = Literal["OPEN", "CLOSE"]

_EXECUTION_MODEL_TO_STAGE: dict[str, EntryStage] = {
    "same_close": "CLOSE", "next_open": "OPEN", "next_close": "CLOSE",
}


def event_study_forward_returns(
    price_df: pd.DataFrame, events: pd.DataFrame, entry_stage: EntryStage, horizons: tuple[int, ...] = FORWARD_HORIZONS,
) -> pd.DataFrame:
    """`events` must have columns `Signal_Date`, `Execution_Date`,
    `Execution_Price` (see `run_event_study_all_models` for how these are
    assembled). All horizon/MFE/MAE measurement is anchored on
    `Execution_Date`'s row position in `price_df`, per the module docstring's
    session-stage semantics -- NEVER on `Signal_Date`'s position."""
    idx = price_df.index
    rows = []
    max_h = max(horizons)
    open_stage = entry_stage == "OPEN"

    for _, ev in events.iterrows():
        signal_date, execution_date, entry_price = ev["Signal_Date"], ev["Execution_Date"], ev["Execution_Price"]
        if execution_date not in idx or pd.isna(entry_price):
            continue
        loc = idx.get_loc(execution_date)
        row = {"Signal_Date": signal_date, "Execution_Date": execution_date, "Entry_Price": entry_price}

        mfe_start_loc = loc if open_stage else loc + 1
        mfe_end_loc = min((loc + max_h - 1) if open_stage else (loc + max_h), len(idx) - 1)
        if mfe_start_loc <= mfe_end_loc:
            path = price_df.iloc[mfe_start_loc : mfe_end_loc + 1]
            row["MFE_Pct"] = (path["High"].max() - entry_price) / entry_price * 100.0
            row["MAE_Pct"] = (path["Low"].min() - entry_price) / entry_price * 100.0
            row["Time_to_MFE"] = int(path["High"].to_numpy().argmax()) + (mfe_start_loc - loc)
            row["Time_to_MAE"] = int(path["Low"].to_numpy().argmin()) + (mfe_start_loc - loc)
        else:
            row["MFE_Pct"] = row["MAE_Pct"] = row["Time_to_MFE"] = row["Time_to_MAE"] = float("nan")

        for h in horizons:
            # OPEN stage: H=1 is the SAME (execution) session's close.
            # CLOSE stage: H=1 is the FOLLOWING session's close.
            fut_loc = loc + (h - 1) if open_stage else loc + h
            row[f"Fwd_Ret_{h}D"] = (
                (price_df["Close"].iloc[fut_loc] - entry_price) / entry_price * 100.0
                if 0 <= fut_loc < len(idx) else float("nan")
            )
        rows.append(row)
    return pd.DataFrame(rows)


def apply_transaction_costs(event_study_df: pd.DataFrame, costs: CostsConfig, horizons: tuple[int, ...] = FORWARD_HORIZONS, scenario: str = "base_cost") -> pd.DataFrame:
    out = event_study_df.copy()
    round_trip_cost_pct = compute_round_trip_cost_pct(costs, scenario=scenario) * 100.0
    for h in horizons:
        col = f"Fwd_Ret_{h}D"
        if col in out.columns:
            out[f"{col}_Net"] = out[col] - round_trip_cost_pct
    out.attrs["round_trip_cost_pct"] = round_trip_cost_pct
    out.attrs["cost_scenario"] = scenario
    return out


def run_event_study_all_models(
    feature_frames: dict[str, pd.DataFrame], calendar: NSECalendar, costs: CostsConfig,
    execution_model: ExecutionModel = "next_open",
    horizons: tuple[int, ...] = FORWARD_HORIZONS, cost_scenario: str = "base_cost",
) -> pd.DataFrame:
    entry_stage = _EXECUTION_MODEL_TO_STAGE[execution_model]
    all_rows = []
    for model_col, model_label in ENTRY_MODEL_COLS.items():
        for ticker, feats in feature_frames.items():
            if model_col not in feats.columns:
                continue
            signal_dates = feats.index[feats[model_col].fillna(False)]
            if len(signal_dates) == 0:
                continue
            events = []
            for sd in signal_dates:
                exe = resolve_execution_price(feats, sd, calendar, execution_model=execution_model)
                if exe.status == "OK" and exe.execution_price is not None:
                    events.append({"Signal_Date": sd, "Execution_Date": exe.execution_date, "Execution_Price": exe.execution_price})
            if not events:
                continue
            events_df = pd.DataFrame(events)
            es = event_study_forward_returns(feats, events_df, entry_stage=entry_stage, horizons=horizons)
            if es.empty:
                continue
            es["Ticker"], es["Entry_Model"], es["Entry_Model_Label"] = ticker, model_col, model_label
            es["Execution_Model"] = execution_model
            es["Market_Regime"] = feats.loc[es["Execution_Date"], "Market_Regime"].to_numpy()
            all_rows.append(es)
    if not all_rows:
        return pd.DataFrame()
    combined = pd.concat(all_rows, ignore_index=True)
    return apply_transaction_costs(combined, costs, horizons=horizons, scenario=cost_scenario)


def comparison_table(event_df: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    from ema_scanner.research.statistics import performance_stats

    if event_df.empty:
        return pd.DataFrame()
    col, col_net = f"Fwd_Ret_{horizon}D", f"Fwd_Ret_{horizon}D_Net"
    rows = []
    for model_col, model_label in ENTRY_MODEL_COLS.items():
        sub = event_df[event_df["Entry_Model"] == model_col]
        if sub.empty:
            continue
        stats = performance_stats(sub[col])
        stats_net = performance_stats(sub[col_net]) if col_net in sub.columns else {}
        rows.append({
            "Entry_Definition": model_label, "N_Occurrences": stats.get("n_trades", 0),
            f"{horizon}D_Win_Rate_Pct": stats.get("win_rate_pct"), f"{horizon}D_Median_Return_Pct": stats.get("median_return_pct"),
            f"{horizon}D_Avg_Return_Pct_Gross": stats.get("avg_return_pct"), f"{horizon}D_Avg_Return_Pct_Net": stats_net.get("avg_return_pct"),
            "Max_Favorable_Excursion_Pct": sub["MFE_Pct"].mean(), "Max_Adverse_Excursion_Pct": sub["MAE_Pct"].mean(),
            # NOTE: no "Max_Drawdown_Pct" here by design (Phase-2 Section 15) --
            # event-study observations are not a chronological, mutually-
            # exclusive path; see research/statistics.py::portfolio_stats_from_equity_curve.
        })
    return pd.DataFrame(rows)


def regime_breakdown(event_df: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """MANDATORY bull/neutral/bear breakdown per entry model (brief Section 48/55)."""
    from ema_scanner.research.statistics import performance_stats

    if event_df.empty:
        return pd.DataFrame()
    col = f"Fwd_Ret_{horizon}D"
    rows = []
    for model_col, model_label in ENTRY_MODEL_COLS.items():
        for regime in ["BULL", "NEUTRAL", "BEAR"]:
            sub = event_df[(event_df["Entry_Model"] == model_col) & (event_df["Market_Regime"] == regime)]
            if sub.empty:
                continue
            stats = performance_stats(sub[col])
            stats["Entry_Definition"], stats["Regime"] = model_label, regime
            rows.append(stats)
    return pd.DataFrame(rows)


def stock_concentration_check(event_df: pd.DataFrame) -> pd.DataFrame:
    """Is the result driven by one stock? (brief Section 51/80)."""
    if event_df.empty:
        return pd.DataFrame()
    counts = event_df.groupby(["Entry_Model", "Ticker"]).size().rename("n_signals").reset_index()
    counts = counts.sort_values(["Entry_Model", "n_signals"], ascending=[True, False])
    totals = counts.groupby("Entry_Model")["n_signals"].transform("sum")
    counts["share_of_model_pct"] = counts["n_signals"] / totals * 100.0
    return counts
