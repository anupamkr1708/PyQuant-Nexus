"""Historical event study (notebook Cell 38; audit row 30).

Answers "what happened after these signals?" — explicitly NOT a tradable
portfolio P&L (brief Section 46). For that, see research/backtest.py, which is a
SEPARATE engine. Do not mix the two outputs into one table.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.execution.costs import CostsConfig, compute_round_trip_cost_pct
from ema_scanner.execution.execution_models import resolve_execution_price
from ema_scanner.strategy.entries import ENTRY_MODEL_COLS

FORWARD_HORIZONS = (1, 3, 5, 10, 20, 40)


def event_study_forward_returns(
    price_df: pd.DataFrame, event_dates, entry_prices: pd.Series, horizons: tuple[int, ...] = FORWARD_HORIZONS
) -> pd.DataFrame:
    idx = price_df.index
    rows = []
    max_h = max(horizons)
    for event_date in event_dates:
        if event_date not in entry_prices.index or pd.isna(entry_prices.loc[event_date]) or event_date not in idx:
            continue
        entry_price = entry_prices.loc[event_date]
        loc = idx.get_loc(event_date)
        row = {"Event_Date": event_date, "Entry_Price": entry_price}
        path = price_df.iloc[loc : min(loc + max_h, len(idx) - 1) + 1]
        if len(path) > 1:
            row["MFE_Pct"] = (path["High"].iloc[1:].max() - entry_price) / entry_price * 100.0
            row["MAE_Pct"] = (path["Low"].iloc[1:].min() - entry_price) / entry_price * 100.0
            row["Time_to_MFE"] = int(path["High"].iloc[1:].to_numpy().argmax()) + 1
            row["Time_to_MAE"] = int(path["Low"].iloc[1:].to_numpy().argmin()) + 1
        else:
            row["MFE_Pct"] = row["MAE_Pct"] = row["Time_to_MFE"] = row["Time_to_MAE"] = float("nan")
        for h in horizons:
            fut_loc = loc + h
            row[f"Fwd_Ret_{h}D"] = (
                (price_df["Close"].iloc[fut_loc] - entry_price) / entry_price * 100.0
                if fut_loc < len(idx) else float("nan")
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
    execution_model: Literal["same_close", "next_open", "next_close"] = "next_open",
    horizons: tuple[int, ...] = FORWARD_HORIZONS, cost_scenario: str = "base_cost",
) -> pd.DataFrame:
    all_rows = []
    for model_col, model_label in ENTRY_MODEL_COLS.items():
        for ticker, feats in feature_frames.items():
            if model_col not in feats.columns:
                continue
            event_dates = feats.index[feats[model_col].fillna(False)]
            if len(event_dates) == 0:
                continue
            entry_prices = {}
            for ed in event_dates:
                exe = resolve_execution_price(feats, ed, calendar, execution_model=execution_model)
                if exe.execution_price is not None:
                    entry_prices[ed] = exe.execution_price
            if not entry_prices:
                continue
            es = event_study_forward_returns(feats, pd.Series(entry_prices).index, pd.Series(entry_prices), horizons=horizons)
            if es.empty:
                continue
            es["Ticker"], es["Entry_Model"], es["Entry_Model_Label"] = ticker, model_col, model_label
            es["Market_Regime"] = feats.loc[es["Event_Date"], "Market_Regime"].to_numpy()
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
            # exclusive path, so a drawdown computed from them would not
            # represent an actual tradable portfolio path. See
            # research/statistics.py::portfolio_stats_from_equity_curve for the
            # real (backtest-derived) drawdown metric.
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
