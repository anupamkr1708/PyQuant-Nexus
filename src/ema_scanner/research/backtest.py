"""Stateful portfolio backtest engine (brief Section 49).

**NEW CODE — not present in the notebook, which only implements an event study
(research/event_study.py).** Built to the brief's Section 49 specification:
cash, open positions, entries, exits, stops, position sizing, transaction costs,
a trade log, and a daily equity curve. Labeled `ENGINEERING_DECISION` throughout
because the notebook gives no guidance to preserve here — every design choice
below is new and must be reviewed, not assumed correct (brief Section 99).

**Exit logic (brief Section 50 — do not silently invent one universal exit and
present it as source-derived):**

    exit_rule = "STOP_ONLY_RESEARCH" : the ONLY exit is the swing-based stop
                                        (as of the signal date) or end-of-data.
    exit_rule = "FIXED_HORIZON"      : exit at Close after `fixed_horizon_days`
                                        sessions, OR the stop, whichever comes
                                        first.

Both are labeled RESEARCH_HYPOTHESIS. Neither is "the" exit rule the source note
specifies — the source note only specifies the entry and the stop.

**Stop execution models the gap (brief Section 43):** if a session's Open has
already gapped through the stop, the fill is modeled at Open (`STOP_GAP_THROUGH`),
not at the stop price itself; otherwise, if the session's Low touches the stop,
the fill is modeled at the stop price (`STOP`). No intraday data beyond the
day's own OHLC bar is used, and only what was already known at the start of that
session (the frozen `current_stop`) is used — never a future bar.

**Known simplifications (documented, not hidden):**
- Long-only. The notebook's entry models A-E and the source note's short-side
  reference (point 8) are not implemented as trading logic anywhere in this
  refactor either — see STRATEGY_SPEC.md.
- One open position per symbol at a time.
- New-entry ordering within a single date follows Python dict iteration order
  over the input `feature_frames` (i.e., first-come by construction order), not
  by any ranking or the heuristic score (brief Section 8: the heuristic score is
  never a trading rule).
- Cash is debited/credited at the signal date's processing step using the
  resolved execution price, not literally at the execution date's own bar. This
  does not change what price is used or whether look-ahead occurs; it is a
  bookkeeping simplification of the daily cash timeline.

This engine has NOT been run against real market data in this environment (no
network access to yfinance/NSE here — see RESEARCH_LIMITATIONS.md). It has been
exercised only against synthetic fixtures in tests/unit/test_backtest.py to
confirm accounting invariants (cash + position value reconciles, no negative
cash, stops never widen, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import Config
from ema_scanner.execution.costs import compute_transaction_cost_pct
from ema_scanner.execution.execution_models import resolve_execution_price
from ema_scanner.execution.sizing import position_size
from ema_scanner.models import Trade

ExitRule = Literal["STOP_ONLY_RESEARCH", "FIXED_HORIZON"]


@dataclass
class _OpenPosition:
    symbol: str
    strategy_id: str
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    entry_price: float
    quantity: int
    initial_stop: float
    current_stop: float
    entry_cost: float
    mfe_pct: float = float("-inf")
    mae_pct: float = float("inf")


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.DataFrame  # columns: cash, positions_value, equity
    final_cash: float
    config_summary: dict = field(default_factory=dict)

    def trade_log_df(self) -> pd.DataFrame:
        return pd.DataFrame([vars(t) for t in self.trades])


def run_portfolio_backtest(
    feature_frames: dict[str, pd.DataFrame],
    calendar: NSECalendar,
    cfg: Config,
    entry_model_col: str = "Any_Entry_Triggered",
    exit_rule: ExitRule = "STOP_ONLY_RESEARCH",
    fixed_horizon_days: int = 20,
    initial_capital: float = 1_000_000.0,
    max_concurrent_positions: int = 20,
    cost_scenario: str = "base_cost",
) -> BacktestResult:
    if exit_rule not in ("STOP_ONLY_RESEARCH", "FIXED_HORIZON"):
        raise ValueError(f"Unknown exit_rule: {exit_rule!r} (brief Section 50: no silent invented exits)")

    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(f.index) for f in feature_frames.values()]))) if feature_frames else pd.DatetimeIndex([])
    one_leg_cost_pct = compute_transaction_cost_pct(cfg.costs, scenario=cost_scenario)

    cash = initial_capital
    positions: dict[str, _OpenPosition] = {}
    trades: list[Trade] = []
    equity_rows = []

    def _mark_to_market(date) -> float:
        total = 0.0
        for sym, pos in positions.items():
            feats = feature_frames[sym]
            if date in feats.index:
                px = float(feats.loc[date, "Close"])
            else:
                px = pos.entry_price  # stale fallback; symbol has no bar today
            total += px * pos.quantity
        return total

    def _close_position(sym: str, pos: _OpenPosition, exit_date, exit_price: float, exit_reason: str | None) -> float:
        nonlocal cash
        exit_cost = exit_price * pos.quantity * one_leg_cost_pct
        gross_pnl = (exit_price - pos.entry_price) * pos.quantity
        total_costs = pos.entry_cost + exit_cost
        net_pnl = gross_pnl - total_costs
        holding = int((exit_date - pos.execution_date).days)  # calendar days; session count needs full calendar lookup
        cash += exit_price * pos.quantity - exit_cost
        trades.append(Trade(
            symbol=sym, strategy_id=pos.strategy_id, signal_date=pos.signal_date, execution_date=pos.execution_date,
            entry_price=pos.entry_price, quantity=pos.quantity, initial_stop=pos.initial_stop,
            exit_date=exit_date, exit_price=exit_price, exit_reason=exit_reason,
            gross_pnl=gross_pnl, costs=total_costs, net_pnl=net_pnl,
            return_pct=(exit_price / pos.entry_price - 1.0) * 100.0,
            mae_pct=pos.mae_pct if pos.mae_pct != float("inf") else None,
            mfe_pct=pos.mfe_pct if pos.mfe_pct != float("-inf") else None,
            holding_period_sessions=holding,
        ))
        return net_pnl

    for d in all_dates:
        # 1. Exits
        for sym in list(positions.keys()):
            pos = positions[sym]
            feats = feature_frames[sym]
            if d not in feats.index or d <= pos.execution_date:
                continue
            row = feats.loc[d]
            # track running MFE/MAE while open
            run_ret_high = (float(row["High"]) / pos.entry_price - 1.0) * 100.0
            run_ret_low = (float(row["Low"]) / pos.entry_price - 1.0) * 100.0
            pos.mfe_pct = max(pos.mfe_pct, run_ret_high)
            pos.mae_pct = min(pos.mae_pct, run_ret_low)

            exit_price, exit_reason = None, None
            stop = pos.current_stop
            if pd.notna(stop):
                if float(row["Open"]) <= stop:
                    exit_price, exit_reason = float(row["Open"]), "STOP_GAP_THROUGH"
                elif float(row["Low"]) <= stop:
                    exit_price, exit_reason = float(stop), "STOP"
            if exit_price is None and exit_rule == "FIXED_HORIZON":
                loc_now = feats.index.get_loc(d)
                loc_entry = feats.index.get_loc(pos.execution_date)
                if (loc_now - loc_entry) >= fixed_horizon_days:
                    exit_price, exit_reason = float(row["Close"]), "FIXED_HORIZON"
            if exit_price is not None:
                _close_position(sym, pos, d, exit_price, exit_reason)
                del positions[sym]

        # 2. Entries (only if capacity remains)
        if len(positions) < max_concurrent_positions:
            for sym, feats in feature_frames.items():
                if len(positions) >= max_concurrent_positions:
                    break
                if sym in positions or d not in feats.index:
                    continue
                row = feats.loc[d]
                if not bool(row.get(entry_model_col, False)):
                    continue
                stop_ref = row.get("Swing_Low_Stop")
                if stop_ref is None or pd.isna(stop_ref):
                    continue  # no valid stop -> cannot size the position; skip (brief Section 42)
                exe = resolve_execution_price(feats, d, calendar, execution_model=cfg.execution.model)
                if exe.execution_price is None:
                    continue
                sized = position_size(
                    capital=cash, entry_price=exe.execution_price, stop_price=float(stop_ref),
                    risk_per_trade_pct=cfg.risk.risk_per_trade_pct,
                )
                if sized["qty"] <= 0:
                    continue
                entry_cost = exe.execution_price * sized["qty"] * one_leg_cost_pct
                required_cash = exe.execution_price * sized["qty"] + entry_cost
                if required_cash > cash:
                    continue
                cash -= required_cash
                positions[sym] = _OpenPosition(
                    symbol=sym, strategy_id=entry_model_col, signal_date=d, execution_date=exe.execution_date,
                    entry_price=exe.execution_price, quantity=sized["qty"], initial_stop=float(stop_ref),
                    current_stop=float(stop_ref), entry_cost=entry_cost,
                )

        positions_value = _mark_to_market(d)
        equity_rows.append({"date": d, "cash": cash, "positions_value": positions_value, "equity": cash + positions_value, "open_positions": len(positions)})

    # Close anything still open at the end of the data window.
    if len(all_dates):
        last_date = all_dates[-1]
        for sym in list(positions.keys()):
            pos = positions[sym]
            feats = feature_frames[sym]
            px = float(feats.loc[last_date, "Close"]) if last_date in feats.index else pos.entry_price
            _close_position(sym, pos, last_date, px, "END_OF_DATA")
            del positions[sym]
        if equity_rows:
            equity_rows[-1]["cash"], equity_rows[-1]["positions_value"] = cash, 0.0
            equity_rows[-1]["equity"] = cash
            equity_rows[-1]["open_positions"] = 0

    equity_curve = pd.DataFrame(equity_rows).set_index("date") if equity_rows else pd.DataFrame(
        columns=["cash", "positions_value", "equity", "open_positions"]
    )
    return BacktestResult(
        trades=trades, equity_curve=equity_curve, final_cash=cash,
        config_summary={"entry_model_col": entry_model_col, "exit_rule": exit_rule, "cost_scenario": cost_scenario},
    )
