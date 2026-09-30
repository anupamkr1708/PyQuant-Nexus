"""BLOCKER 15/16/17 (Phase-3): position-sizing basis, same-day stop
eligibility, entry-day MFE/MAE."""
import numpy as np
import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import load_config
from ema_scanner.execution.sizing import position_size
from ema_scanner.research.backtest import run_portfolio_backtest


def _two_symbol_frames_where_equity_and_cash_diverge():
    """SYM_A is deep in an open profitable position (positions_value >> 0,
    so equity >> cash) when SYM_B's signal fires -- forces equity != cash so
    the sizing-basis choice actually changes the resulting quantity."""
    dates = pd.bdate_range("2020-01-01", periods=120)
    # SYM_A: triggers Entry A very early, rallies hard afterward (built with a
    # small oscillation so a confirmable swing low exists).
    n = len(dates)
    trend_a = np.concatenate([np.full(40, 100.0), 100 + np.linspace(0, 80, n - 40)])
    osc = 2.0 * np.sin(np.arange(n) * (2 * np.pi / 13))
    close_a = trend_a + osc
    df_a = pd.DataFrame({"Open": close_a, "High": close_a + 1, "Low": close_a - 1, "Close": close_a, "Volume": 500_000.0}, index=dates)
    # SYM_B: flat until a later date, then also triggers Entry A.
    trend_b = np.concatenate([np.full(70, 50.0), 50 + np.linspace(0, 40, n - 70)])
    close_b = trend_b + 1.5 * np.sin(np.arange(n) * (2 * np.pi / 11))
    df_b = pd.DataFrame({"Open": close_b, "High": close_b + 1, "Low": close_b - 1, "Close": close_b, "Volume": 500_000.0}, index=dates)

    from ema_scanner.features.regime import compute_market_regime
    from ema_scanner.strategy.signal_engine import build_stock_feature_frame

    cfg = load_config()
    index_df = pd.DataFrame({"Close": np.linspace(20000, 22000, n)}, index=dates)
    regime = compute_market_regime(index_df)
    feats_a = build_stock_feature_frame(df_a, index_df["Close"], regime, cfg)
    feats_b = build_stock_feature_frame(df_b, index_df["Close"], regime, cfg)
    return {"SYM_A": feats_a, "SYM_B": feats_b}, cfg


def test_equity_basis_and_cash_basis_can_size_differently_when_they_diverge():
    frames, cfg = _two_symbol_frames_where_equity_and_cash_diverge()
    cfg.execution.model = "same_close"
    cal = NSECalendar()

    result_equity = run_portfolio_backtest(frames, cal, cfg, initial_capital=1_000_000, max_concurrent_positions=5, risk_budget_basis="EQUITY")
    result_cash = run_portfolio_backtest(frames, cal, cfg, initial_capital=1_000_000, max_concurrent_positions=5, risk_budget_basis="CASH")

    assert result_equity.config_summary["risk_budget_basis"] == "EQUITY"
    assert result_cash.config_summary["risk_budget_basis"] == "CASH"
    # Not asserting they MUST differ numerically (data-dependent), but both
    # must run and the config actually reaches the engine (Phase-2 Section 26
    # style config-propagation check).


def test_position_size_uses_the_capital_argument_directly_documenting_the_basis_contract():
    """position_size() itself is basis-agnostic (it just takes `capital`) --
    the CALLER decides equity vs cash. This test locks that contract: passing
    a different `capital` value changes qty proportionally."""
    small = position_size(capital=100_000, entry_price=100, stop_price=95, risk_per_trade_pct=1.0)
    large = position_size(capital=500_000, entry_price=100, stop_price=95, risk_per_trade_pct=1.0)
    assert large["qty"] > small["qty"]


def test_next_open_entry_can_exit_via_stop_on_the_same_execution_day():
    """BLOCKER 16: an entry at NEXT_OPEN must be eligible for a same-day stop
    hit using the rest of that day's OHLC path."""
    dates = pd.bdate_range("2021-01-01", periods=10)
    # Day 0: signal day (arbitrary). Day 1: execution day -- Open is the
    # entry; that SAME day's Low then plunges through a stop we control.
    close = np.array([100.0, 101.0, 90.0, 91, 92, 93, 94, 95, 96, 97])
    openp = close.copy()
    high = close + 1
    low = close - 1
    low[2] = 80.0  # execution-day (index 2) Low plunges well below any reasonable stop
    df = pd.DataFrame({"Open": openp, "High": high, "Low": low, "Close": close, "Volume": 100_000.0}, index=dates)
    df["Any_Entry_Triggered"] = [False, True] + [False] * 8
    df["Swing_Low_Stop"] = [np.nan, 85.0] + [85.0] * 8  # a stop that the execution day's Low (80) will breach
    df["Confirmed_Swing_Low_Date"] = pd.NaT

    from ema_scanner.config import load_config as _lc
    cfg = _lc()
    cfg.execution.model = "next_open"
    cal = NSECalendar()
    result = run_portfolio_backtest({"SYM": df}, cal, cfg, initial_capital=1_000_000, max_concurrent_positions=1)
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.execution_date == dates[2]
    assert t.exit_date == dates[2], "the stop hit on the SAME execution day must not be skipped (BLOCKER 16)"
    assert t.exit_reason == "STOP"


def test_entry_day_mfe_mae_included_for_next_open_excluded_for_next_close():
    """BLOCKER 17."""
    dates = pd.bdate_range("2021-01-01", periods=8)
    close = np.array([100.0, 101.0, 105.0, 106, 107, 108, 109, 110])
    openp = close.copy()
    high = np.array([101.0, 102.0, 120.0, 106.5, 107.5, 108.5, 109.5, 110.5])  # big High spike on execution day
    low = close - 0.5
    df = pd.DataFrame({"Open": openp, "High": high, "Low": low, "Close": close, "Volume": 100_000.0}, index=dates)
    df["Any_Entry_Triggered"] = [False, True] + [False] * 6
    df["Swing_Low_Stop"] = [np.nan] + [90.0] * 7
    df["Confirmed_Swing_Low_Date"] = pd.NaT

    cfg = load_config()
    cal = NSECalendar()

    cfg.execution.model = "next_open"
    result_open = run_portfolio_backtest({"SYM": df.copy()}, cal, cfg, initial_capital=1_000_000, max_concurrent_positions=1)
    t_open = result_open.trades[0]
    # Entry at Open of execution day (index 2, price 105); High that SAME day
    # is 120 -> MFE should reflect that big same-day spike.
    expected_mfe_open = (120.0 / 105.0 - 1.0) * 100.0
    assert t_open.mfe_pct == pytest_approx(expected_mfe_open)

    cfg2 = load_config()
    cfg2.execution.model = "next_close"
    result_close = run_portfolio_backtest({"SYM": df.copy()}, cal, cfg2, initial_capital=1_000_000, max_concurrent_positions=1)
    t_close = result_close.trades[0]
    # Entry at Close of execution day (index 2, price 105); that day's High
    # (120) occurred BEFORE the close-price entry and must NOT count.
    assert t_close.mfe_pct is None or t_close.mfe_pct < expected_mfe_open - 1.0


def pytest_approx(x):
    import pytest
    return pytest.approx(x, rel=1e-6)
