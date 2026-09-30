"""Stateful portfolio backtest engine (brief Section 49; Phase-2 Section 11;
Phase-3 Sections 3, 15, 16, 17 -- all BLOCKER fixes to the execution loop).

**BLOCKER 3 fix (Phase-3):** the previous loop processed "execute pending
orders due today" (step 0) BEFORE "detect today's new signals" (a later
step). For `same_close`, `resolve_execution_price` resolves
`execution_date == signal_date == d` -- so a same_close order created in the
"new signals" step on date `d` was never re-checked against step 0's
`po.execution_date == d` test on ANY later date either (that test only ever
runs once per date, and `d` has already passed by the time the order
exists). **same_close orders never executed at all.** Fixed by giving
`same_close` its own immediate-execution path (`_open_position` called
directly, bypassing the PENDING_ORDER stage entirely) rather than routing it
through the same pending-order queue used by `next_open`/`next_close`.

**BLOCKER 15 fix (Phase-3):** position sizing now uses EQUITY (cash +
mark-to-market value of currently open positions), not raw `cash`, as the
risk-budget basis by default -- matching STRATEGY_SPEC.md Section 8's
documented formula (`equity * risk_per_trade_pct`). `cfg.research.backtest.
risk_budget_basis` can select `CASH` instead as an explicit, non-default
research variant. Available cash is ALWAYS enforced separately as an
affordability constraint either way.

**BLOCKER 16 fix (Phase-3):** exits are no longer unconditionally skipped on
`d == execution_date`. For a `next_open` fill, entry occurs AT that day's
Open -- the REST of that same session's OHLC path (High/Low/Close after the
open) is real, already-known information and must be eligible for a same-day
stop hit (checked via `Low <= stop`, with NO gap-through-open logic, since
the entry price itself was already validated to sit on the correct side of
the stop at fill time -- there is no overnight gap to speak of on the entry
day itself). For a `close`-stage fill (`same_close`/`next_close`), entry
occurs AT that day's close, so there is genuinely no more price path left
that session -- the entry day is correctly excluded from exits, and the
gap-through-open check resumes normally from the NEXT session onward.

**BLOCKER 17 fix (Phase-3):** MFE/MAE tracking now starts on the entry day
itself for `OPEN`-stage fills (that day's High/Low, relative to entry_price,
are valid post-entry observations), and starts only from the FOLLOWING
session for `CLOSE`-stage fills (that day's own High/Low occurred BEFORE the
close-price entry and must not be counted as post-entry excursion).

Everything else (swing audit trail, side-aware costs, DATA_GAP handling, risk
geometry validation, end-of-data close-at-own-last-bar) is unchanged from the
Phase-2 version -- see docs/PHASE2_AUDIT.md / docs/PHASE3_AUDIT.md.

**Known, still-documented simplifications:** long-only; one open position per
symbol; new-signal ordering within a date follows Python dict iteration order
over `feature_frames`. This engine has NOT been run against real market data
in this environment (no network access here -- see RESEARCH_LIMITATIONS.md).
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
EntryStage = Literal["OPEN", "CLOSE"]


@dataclass
class _PendingOrder:
    """Only used for next_open/next_close, where execution genuinely happens
    on a LATER date than the signal. same_close never creates one of these --
    see BLOCKER 3 fix in the module docstring."""

    symbol: str
    strategy_id: str
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    price_field: Literal["Open", "Close"]
    stop_reference: float
    stop_source_swing_date: pd.Timestamp | None
    stop_available_date: pd.Timestamp | None


@dataclass
class _OpenPosition:
    symbol: str
    strategy_id: str
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    entry_stage: EntryStage
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


_EXECUTION_MODEL_TO_STAGE: dict[str, EntryStage] = {
    "same_close": "CLOSE", "next_open": "OPEN", "next_close": "CLOSE",
}
_EXECUTION_MODEL_TO_FIELD: dict[str, Literal["Open", "Close"]] = {
    "same_close": "Close", "next_open": "Open", "next_close": "Close",
}


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
    risk_budget_basis: Literal["EQUITY", "CASH"] | None = None,
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
    risk_budget_basis = risk_budget_basis or bt_cfg.risk_budget_basis

    if exit_rule not in ("STOP_ONLY_RESEARCH", "FIXED_HORIZON"):
        raise ValueError(f"Unknown exit_rule: {exit_rule!r} (brief Section 50: no silent invented exits)")

    execution_model = cfg.execution.model
    entry_stage = _EXECUTION_MODEL_TO_STAGE[execution_model]
    price_field = _EXECUTION_MODEL_TO_FIELD[execution_model]

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

    def _current_equity(date) -> float:
        return cash + _mark_to_market(date)

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

    def _try_open_position(
        sym: str, strategy_id: str, signal_date, execution_date, stage: EntryStage, entry_price: float,
        stop_reference: float, stop_source_swing_date, stop_available_date, processing_date,
    ) -> bool:
        """Shared open-position logic (BLOCKER 3: called from BOTH the
        pending-order-due-today path AND the same_close immediate-execution
        path, so both go through IDENTICAL geometry/sizing/cash logic)."""
        nonlocal cash
        if not validate_risk_geometry(entry_price, stop_reference, "LONG"):
            skipped.append(SkippedSignal(sym, processing_date, "invalid_risk_geometry"))
            return False
        # BLOCKER 15: risk-budget basis is EQUITY by default (matches
        # STRATEGY_SPEC.md), not raw cash -- selectable via config.
        risk_capital_basis = _current_equity(processing_date) if risk_budget_basis == "EQUITY" else cash
        sized = position_size(capital=risk_capital_basis, entry_price=entry_price, stop_price=stop_reference,
                               risk_per_trade_pct=cfg.risk.risk_per_trade_pct, min_qty=minimum_trade_qty)
        if sized["qty"] <= 0:
            skipped.append(SkippedSignal(sym, processing_date, sized["reason"]))
            return False
        max_qty_by_position_cap = int((risk_capital_basis * max_position_pct_of_equity / 100.0) // entry_price)
        qty = min(sized["qty"], max_qty_by_position_cap) if max_position_pct_of_equity < 100.0 else sized["qty"]
        if qty <= 0:
            skipped.append(SkippedSignal(sym, processing_date, "capacity_full"))
            return False
        entry_cost = entry_price * qty * buy_cost_pct
        required_cash = entry_price * qty + entry_cost
        if required_cash > cash:  # affordability is ALWAYS a cash constraint, regardless of sizing basis
            skipped.append(SkippedSignal(sym, processing_date, "insufficient_cash"))
            return False
        cash -= required_cash
        positions[sym] = _OpenPosition(
            symbol=sym, strategy_id=strategy_id, signal_date=signal_date, execution_date=execution_date,
            entry_stage=stage, entry_price=entry_price, quantity=qty, initial_stop=stop_reference,
            current_stop=stop_reference, entry_cost=entry_cost,
            stop_source_swing_date=stop_source_swing_date, stop_available_date=stop_available_date,
        )
        return True

    for d in all_dates:
        # --- 0. Execute pending orders (next_open/next_close) due today ---
        for sym in list(pending_orders.keys()):
            po = pending_orders[sym]
            if po.execution_date != d:
                continue
            del pending_orders[sym]
            feats = feature_frames[sym]
            if d not in feats.index:
                skipped.append(SkippedSignal(sym, d, "data_gap"))
                continue
            entry_price = float(feats.loc[d, po.price_field])
            _try_open_position(
                sym, po.strategy_id, po.signal_date, d, entry_stage, entry_price,
                po.stop_reference, po.stop_source_swing_date, po.stop_available_date, d,
            )

        # --- 1. New SIGNALS today ---
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
                swing_date, swing_avail = row.get("Confirmed_Swing_Low_Date"), row.get("Confirmed_Swing_Low_Date")

                if execution_model == "same_close":
                    # BLOCKER 3 fix: execute IMMEDIATELY, same date, same
                    # processing pass -- never routed through pending_orders,
                    # which is exactly the queue that was silently swallowing
                    # same_close orders before this fix.
                    entry_price = float(row["Close"])
                    _try_open_position(sym, entry_model_col, d, d, "CLOSE", entry_price, float(stop_ref), swing_date, swing_avail, d)
                    continue

                exe = resolve_execution_price(feats, d, calendar, execution_model=execution_model)
                if exe.status == "DATA_GAP" or exe.execution_date is None:
                    skipped.append(SkippedSignal(sym, d, "data_gap"))
                    continue
                pending_orders[sym] = _PendingOrder(
                    symbol=sym, strategy_id=entry_model_col, signal_date=d, execution_date=exe.execution_date,
                    price_field=price_field, stop_reference=float(stop_ref),
                    stop_source_swing_date=swing_date, stop_available_date=swing_avail,
                )

        # --- 2. Exits: unified over ALL currently-open positions, including
        # ones opened in steps 0/1 above THIS SAME date (BLOCKER 16: no
        # blanket `d <= execution_date` skip -- eligibility depends on
        # entry_stage, not just the date comparison). ---
        for sym in list(positions.keys()):
            pos = positions[sym]
            feats = feature_frames[sym]
            if d not in feats.index:
                continue
            if d == pos.execution_date and pos.entry_stage == "CLOSE":
                continue  # entry happened AT this day's close -- no price path left that session
            row = feats.loc[d]

            same_day_open_entry = (d == pos.execution_date and pos.entry_stage == "OPEN")
            # BLOCKER 17: MFE/MAE starts on the entry day itself for OPEN-stage
            # fills; only from the day AFTER entry for CLOSE-stage fills
            # (already guaranteed by the `continue` above for d==execution_date+CLOSE).
            pos.mfe_pct = max(pos.mfe_pct, (float(row["High"]) / pos.entry_price - 1.0) * 100.0)
            pos.mae_pct = min(pos.mae_pct, (float(row["Low"]) / pos.entry_price - 1.0) * 100.0)

            exit_price, exit_reason = None, None
            stop = pos.current_stop
            if pd.notna(stop):
                if same_day_open_entry:
                    # BLOCKER 16: entry occurred AT this day's Open, which was
                    # already validated (validate_risk_geometry) to be on the
                    # correct side of the stop -- there is no "overnight gap"
                    # to speak of on the entry day itself, so only a plain
                    # intraday Low<=stop check applies (no gap-through-open).
                    if float(row["Low"]) <= stop:
                        exit_price, exit_reason = float(stop), "STOP"
                else:
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
            "risk_budget_basis": risk_budget_basis, "execution_model": execution_model,
        },
    )
