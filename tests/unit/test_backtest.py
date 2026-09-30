"""Backtest engine accounting invariants (new code — research/backtest.py; see
docs/NOTEBOOK_AUDIT.md §5.1). Exercised only against synthetic fixtures."""

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import load_config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.research.backtest import run_portfolio_backtest
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from tests.fixtures.synthetic import make_synthetic_ohlcv


def _build_universe(n_symbols=3, n_days=800):
    cfg = load_config()
    index_df = make_synthetic_ohlcv(n_days, seed=100)[["Close"]]
    regime = compute_market_regime(index_df)
    frames = {}
    for i in range(n_symbols):
        daily = make_synthetic_ohlcv(n_days, seed=200 + i, drift=0.04)
        frames[f"SYM{i}"] = build_stock_feature_frame(daily, index_df["Close"], regime, cfg)
    return frames, cfg


def test_cash_never_goes_negative():
    frames, cfg = _build_universe()
    cal = NSECalendar()
    result = run_portfolio_backtest(frames, cal, cfg, initial_capital=500_000, max_concurrent_positions=5)
    assert (result.equity_curve["cash"] >= 0).all()


def test_equity_curve_reconciles_with_cash_plus_positions():
    frames, cfg = _build_universe()
    cal = NSECalendar()
    result = run_portfolio_backtest(frames, cal, cfg, initial_capital=500_000)
    ec = result.equity_curve
    assert ((ec["equity"] - (ec["cash"] + ec["positions_value"])).abs() < 1e-6).all()


def test_no_open_positions_remain_after_backtest_ends():
    frames, cfg = _build_universe()
    cal = NSECalendar()
    result = run_portfolio_backtest(frames, cal, cfg, initial_capital=500_000)
    if len(result.equity_curve):
        assert result.equity_curve["open_positions"].iloc[-1] == 0


def test_every_trade_has_an_exit_reason():
    frames, cfg = _build_universe()
    cal = NSECalendar()
    result = run_portfolio_backtest(frames, cal, cfg, initial_capital=500_000)
    assert len(result.trades) > 0, "fixture must guarantee at least one trade, or this test passes vacuously"
    for t in result.trades:
        assert t.exit_reason is not None
        assert t.exit_date is not None


def test_unknown_exit_rule_rejected():
    import pytest
    frames, cfg = _build_universe(n_symbols=1, n_days=100)
    cal = NSECalendar()
    with pytest.raises(ValueError):
        run_portfolio_backtest(frames, cal, cfg, exit_rule="MADE_UP_RULE")
