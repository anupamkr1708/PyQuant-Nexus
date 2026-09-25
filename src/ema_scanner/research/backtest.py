"""Stateful portfolio backtest engine (brief Section 49; Phase-2 Section 11 --
BLOCKER rewrite of the execution timeline; Section 29 end-of-data fix).

**Bug fixed (Phase-2 Section 11):** v1 opened an `_OpenPosition` (debiting
cash, marking the position economically active) at the moment a signal was
detected on date `d`, even when the execution model was `next_open`/
`next_close` -- meaning a position dated at `d`'s processing step was carrying
an `execution_date` one session later, but was ALREADY affecting `cash` and
`positions_value` (hence exposure/equity) on `d` itself. That is future
exposure leaking into a past valuation.

Fixed with an explicit state machine:

    SIGNAL (date d, using only data known as of d's close)
      -> PENDING_ORDER (no cash debit, no position, NOT counted in exposure)
      -> EXECUTED (on execution_date: cash debited HERE, position opens HERE)
      -> OPEN_POSITION
      -> EXIT_PENDING / EXIT (stop, fixed horizon, or end-of-data)
      -> CLOSED

For `same_close`, `PENDING_ORDER` and `EXECUTED` collapse onto the same date
(no real "pending" period), which is correct: brief Section 40 defines
`same_close` as "signal date == execution date".

**Bug fixed (Phase-2 Section 12):** `resolve_execution_price` returning
`status="DATA_GAP"` (no positional fallback -- see execution_models.py) is now
respected: a pending order that hits a data gap is DROPPED, not silently
executed against an arbitrary row.

**Bug fixed (Phase-2 Section 13):** every position open is now preceded by an
explicit `validate_risk_geometry` check; an invalid geometry is recorded as a
skipped signal with `reason="invalid_risk_geometry"`, never opened.

**Bug fixed (Phase-2 Section 29):** at the end of the data window, a still-open
position is closed at ITS OWN last valid available Close at-or-before the
backtest's end date (not at `pos.entry_price`, which was a silent, misleading
fallback when a stock's own data ended earlier than the overall backtest
window). If a symbol has genuinely no valid bar at all in that situation
(should not happen given it has an open position from that same feature
frame, but guarded anyway), the trade is closed at entry price ONLY as an
explicit, labeled `END_OF_DATA_NO_VALID_BAR` fallback -- never silently.

**Phase-2 Section 20 (swing stop audit trail):** every `Trade` now records
`stop_source_swing_date` and `stop_available_date` (the swing's own
confirmation date) alongside the stop price actually used.

**Phase-2 Section 17 (side-aware costs):** entry cost uses the BUY-side rate,
exit cost uses the SELL-side rate, rather than one flat `one_leg_cost_pct`
applied to both.

**Phase-2 Section 14:** initial_capital / max_concurrent_positions /
max_position_pct_of_equity / fixed_horizon_days / minimum_trade_qty /
exit_rule / entry_model_col / cost_scenario are ALL sourced from
`cfg.research.backtest` by default now (still overridable per-call for
research flexibility, e.g. walk-forward/sensitivity sweeps) -- none is a
hidden function-body default the caller can't see in config.

**Known, still-documented simplifications (unchanged from v1):** long-only;
one open position per symbol; new-PENDING_ORDER ordering within a date follows
Python dict iteration order over `feature_frames`. This engine has NOT been
run against real market data in this environment (no network access here --
see RESEARCH_LIMITATIONS.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import Config
from ema_scanner.execution.costs import compute_transaction_cost_pct
from ema_scanner.execution.execution_models import resolve_execution_price
from ema_scanner.execution.sizing import position_size, validate_risk_geometry
from ema_scanner.models import Trade

ExitRule = Literal["STOP_ONLY_RESEARCH", "FIXED_HORIZON"]


@dataclass
class _PendingOrder:
    symbol: str
    strategy_id: str
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    stop_reference: float
    stop_source_swing_date: pd.Timestamp | None
    stop_available_date: pd.Timestamp | None


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
    stop_source_swing_date: pd.Timestamp | None
    stop_available_date: pd.Timestamp | None
    mfe_pct: float = float("-inf")
    mae_pct: float = float("inf")


@dataclass
class SkippedSignal:
    symbol: str
    date: pd.Timestamp
    reason: str  # "invalid_risk_geometry" | "data_gap" | "insufficient_cash" | "capacity_full" | "no_stop_reference"


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.DataFrame  # columns: cash, positions_value, equity, open_positions
    final_cash: float
    skipped_signals: list[SkippedSignal] = field(default_factory=list)
    config_summary: dict = field(default_factory=dict)

    def trade_log_df(self) -> pd.DataFrame:
        return pd.DataFrame([vars(t) for t in self.trades])

    def skipped_signals_df(self) -> pd.DataFrame:
        return pd.DataFrame([vars(s) for s in self.skipped_signals])

    def portfolio_stats(self) -> dict:
        """Delegates to research/statistics.py's chronologically-correct
        portfolio metrics (Phase-2 Section 15) -- NEVER computed from
        unordered event returns."""
        from ema_scanner.research.statistics import portfolio_stats_from_equity_curve

        return portfolio_stats_from_equity_curve(self.equity_curve, self.trade_log_df())


def run_portfolio_backtest(
    feature_frames: dict[str, pd.DataFrame],
    calendar: NSECalendar,
    cfg: Config,
    entry_model_col: str | None = None,
    exit_rule: ExitRule | None = None,
    fixed_horizon_days: int | None = None,
    initial_capital: float | None = None,
    max_concurrent_positions: int | None = None,
    max_position_pct_of_equity: float | None = None,
    minimum_trade_qty: int | None = None,
    cost_scenario: str | None = None,
) -> BacktestResult:
    bt_cfg = cfg.research.backtest
    entry_model_col = entry_model_col or bt_cfg.entry_model_col
    exit_rule = exit_rule or bt_cfg.exit_rule
    fixed_horizon_days = fixed_horizon_days if fixed_horizon_days is not None else bt_cfg.fixed_horizon_days
    initial_capital = initial_capital if initial_capital is not None else bt_cfg.initial_capital
    max_concurrent_positions = max_concurrent_positions if max_concurrent_positions is not None else bt_cfg.max_concurrent_positions
    max_position_pct_of_equity = max_position_pct_of_equity if max_position_pct_of_equity is not None else bt_cfg.max_position_pct_of_equity
    minimum_trade_qty = minimum_trade_qty if minimum_trade_qty is not None else bt_cfg.minimum_trade_qty
    cost_scenario = cost_scenario or bt_cfg.cost_scenario

    if exit_rule not in ("STOP_ONLY_RESEARCH", "FIXED_HORIZON"):
        raise ValueError(f"Unknown exit_rule: {exit_rule!r} (brief Section 50: no silent invented exits)")

    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(f.index) for f in feature_frames.values()]))) if feature_frames else pd.DatetimeIndex([])
    buy_cost_pct = compute_transaction_cost_pct(cfg.costs, scenario=cost_scenario, side="buy")
    sell_cost_pct = compute_transaction_cost_pct(cfg.costs, scenario=cost_scenario, side="sell")

    cash = initial_capital
    pending_orders: dict[str, _PendingOrder] = {}
    positions: dict[str, _OpenPosition] = {}
    trades: list[Trade] = []
    skipped: list[SkippedSignal] = []
    equity_rows = []

    def _mark_to_market(date) -> float:
        total = 0.0
        for sym, pos in positions.items():
            feats = feature_frames[sym]
            px = float(feats.loc[date, "Close"]) if date in feats.index else pos.entry_price
            total += px * pos.quantity
        return total

    def _last_valid_close_at_or_before(sym: str, date) -> tuple[float, bool]:
        feats = feature_frames[sym]
        eligible = feats.loc[:date]
        if eligible.empty:
            return float("nan"), False
        return float(eligible["Close"].iloc[-1]), True

    def _close_position(sym: str, pos: _OpenPosition, exit_date, exit_price: float, exit_reason: str | None) -> None:
        nonlocal cash
        exit_cost = exit_price * pos.quantity * sell_cost_pct
        gross_pnl = (exit_price - pos.entry_price) * pos.quantity
        total_costs = pos.entry_cost + exit_cost
        net_pnl = gross_pnl - total_costs
        holding = int(len(feature_frames[sym].loc[pos.execution_date:exit_date]) - 1)
        cash += exit_price * pos.quantity - exit_cost
        trades.append(Trade(
            symbol=sym, strategy_id=pos.strategy_id, signal_date=pos.signal_date, execution_date=pos.execution_date,
            entry_price=pos.entry_price, quantity=pos.quantity, initial_stop=pos.initial_stop,
            exit_date=exit_date, exit_price=exit_price, exit_reason=exit_reason,
            gross_pnl=gross_pnl, costs=total_costs, net_pnl=net_pnl,
            return_pct=(exit_price / pos.entry_price - 1.0) * 100.0,
            mae_pct=pos.mae_pct if pos.mae_pct != float("inf") else None,
            mfe_pct=pos.mfe_pct if pos.mfe_pct != float("-inf") else None,
            holding_period_sessions=max(holding, 0),
            stop_source_swing_date=pos.stop_source_swing_date, stop_available_date=pos.stop_available_date,
        ))

    for d in all_dates:
        # --- 0. Execute pending orders scheduled for today (PENDING_ORDER -> EXECUTED) ---
        for sym in list(pending_orders.keys()):
            po = pending_orders[sym]
            if po.execution_date != d:
                continue
            del pending_orders[sym]
            feats = feature_frames[sym]
            if d not in feats.index:
                skipped.append(SkippedSignal(sym, d, "data_gap"))
                continue
            entry_price = float(feats.loc[d, "Open"]) if po.execution_date != po.signal_date else float(feats.loc[d, "Close"])
            if not validate_risk_geometry(entry_price, po.stop_reference, "LONG"):
                skipped.append(SkippedSignal(sym, d, "invalid_risk_geometry"))
                continue
            sized = position_size(capital=cash, entry_price=entry_price, stop_price=po.stop_reference,
                                   risk_per_trade_pct=cfg.risk.risk_per_trade_pct, min_qty=minimum_trade_qty)
            if sized["qty"] <= 0:
                skipped.append(SkippedSignal(sym, d, sized["reason"]))
                continue
            max_qty_by_position_cap = int((cash * max_position_pct_of_equity / 100.0) // entry_price)
            qty = min(sized["qty"], max_qty_by_position_cap) if max_position_pct_of_equity < 100.0 else sized["qty"]
            if qty <= 0:
                skipped.append(SkippedSignal(sym, d, "capacity_full"))
                continue
            entry_cost = entry_price * qty * buy_cost_pct
            required_cash = entry_price * qty + entry_cost
            if required_cash > cash:
                skipped.append(SkippedSignal(sym, d, "insufficient_cash"))
                continue
            cash -= required_cash
            positions[sym] = _OpenPosition(
                symbol=sym, strategy_id=po.strategy_id, signal_date=po.signal_date, execution_date=d,
                entry_price=entry_price, quantity=qty, initial_stop=po.stop_reference, current_stop=po.stop_reference,
                entry_cost=entry_cost, stop_source_swing_date=po.stop_source_swing_date,
                stop_available_date=po.stop_available_date,
            )

        # --- 1. Exits for already-OPEN positions (unaffected by today's new signals) ---
        for sym in list(positions.keys()):
            pos = positions[sym]
            feats = feature_frames[sym]
            if d not in feats.index or d <= pos.execution_date:
                continue
            row = feats.loc[d]
            pos.mfe_pct = max(pos.mfe_pct, (float(row["High"]) / pos.entry_price - 1.0) * 100.0)
            pos.mae_pct = min(pos.mae_pct, (float(row["Low"]) / pos.entry_price - 1.0) * 100.0)

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

        # --- 2. New SIGNALS -> PENDING_ORDER (no cash/position impact yet) ---
        if len(positions) + len(pending_orders) < max_concurrent_positions:
            for sym, feats in feature_frames.items():
                if len(positions) + len(pending_orders) >= max_concurrent_positions:
                    break
                if sym in positions or sym in pending_orders or d not in feats.index:
                    continue
                row = feats.loc[d]
                if not bool(row.get(entry_model_col, False)):
                    continue
                stop_ref = row.get("Swing_Low_Stop")
                if stop_ref is None or pd.isna(stop_ref):
                    skipped.append(SkippedSignal(sym, d, "no_stop_reference"))
                    continue
                exe = resolve_execution_price(feats, d, calendar, execution_model=cfg.execution.model)
                if exe.status == "DATA_GAP" or exe.execution_date is None:
                    skipped.append(SkippedSignal(sym, d, "data_gap"))
                    continue
                pending_orders[sym] = _PendingOrder(
                    symbol=sym, strategy_id=entry_model_col, signal_date=d, execution_date=exe.execution_date,
                    stop_reference=float(stop_ref), stop_source_swing_date=row.get("Confirmed_Swing_Low_Date"),
                    stop_available_date=row.get("Confirmed_Swing_Low_Date"),
                )

        # --- 3. Mark to market: PENDING_ORDERS contribute NOTHING (no exposure before execution) ---
        positions_value = _mark_to_market(d)
        equity_rows.append({
            "date": d, "cash": cash, "positions_value": positions_value, "equity": cash + positions_value,
            "open_positions": len(positions), "pending_orders": len(pending_orders),
        })

    # End of data: close remaining OPEN positions at EACH SYMBOL'S OWN last
    # valid bar at-or-before the overall backtest end (Phase-2 Section 29 fix
    # -- never at pos.entry_price as a silent fallback).
    if len(all_dates):
        last_date = all_dates[-1]
        for sym in list(positions.keys()):
            pos = positions[sym]
            px, found = _last_valid_close_at_or_before(sym, last_date)
            if found:
                _close_position(sym, pos, last_date, px, "END_OF_DATA_SYMBOL")
            else:
                _close_position(sym, pos, last_date, pos.entry_price, "END_OF_DATA_NO_VALID_BAR")
            del positions[sym]
        # Any PENDING orders never executed by the end of the data window are
        # simply dropped -- they never had cash/position impact, so nothing to unwind.
        pending_orders.clear()
        if equity_rows:
            equity_rows[-1]["cash"], equity_rows[-1]["positions_value"] = cash, 0.0
            equity_rows[-1]["equity"], equity_rows[-1]["open_positions"] = cash, 0

    equity_curve = pd.DataFrame(equity_rows).set_index("date") if equity_rows else pd.DataFrame(
        columns=["cash", "positions_value", "equity", "open_positions", "pending_orders"]
    )
    return BacktestResult(
        trades=trades, equity_curve=equity_curve, final_cash=cash, skipped_signals=skipped,
        config_summary={
            "entry_model_col": entry_model_col, "exit_rule": exit_rule, "cost_scenario": cost_scenario,
            "initial_capital": initial_capital, "max_concurrent_positions": max_concurrent_positions,
        },
    )
