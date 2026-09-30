"""BLOCKER 3 (Phase-3): same_close signals must actually execute.

This test uses a DETERMINISTIC fixture engineered to guarantee at least one
Entry-A (fresh bullish alignment) trigger, rather than hoping synthetic random
data happens to produce one. It must FAIL if same_close signals are silently
discarded (the exact bug this test exists to catch).
"""
import numpy as np
import pandas as pd
import pytest

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import load_config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.research.backtest import run_portfolio_backtest
from ema_scanner.strategy.signal_engine import build_stock_feature_frame


def _deterministic_bullish_alignment_fixture(n=500):
    """Flat-then-rising price series specifically engineered to force a clean
    EMA10>EMA20>EMA89>EMA200 fresh-alignment crossover (Entry A) partway
    through, with no randomness. A small deterministic oscillation is added
    on top of the uptrend so genuine local minima (confirmable swing lows)
    exist before the entry signal -- a purely monotonic ramp has NO local
    minima at all (the window minimum is always its own first bar), which
    would leave Swing_Low_Stop permanently NaN and mask real behavior behind
    a `no_stop_reference` skip rather than testing execution itself."""
    dates = pd.bdate_range("2019-01-01", periods=n)
    flat = np.full(150, 100.0)
    ramp = 100.0 + np.linspace(0, 150, n - 150) ** 1.15  # strong sustained uptrend
    trend = np.concatenate([flat, ramp])
    oscillation = 2.5 * np.sin(np.arange(n) * (2 * np.pi / 17))  # deterministic small pullbacks/rallies
    close = trend + oscillation
    high = close + 1.0
    low = close - 1.0
    openp = close.copy()
    df = pd.DataFrame({"Open": openp, "High": high, "Low": low, "Close": close, "Volume": 500_000.0}, index=dates)
    return df


@pytest.fixture
def guaranteed_signal_frames():
    cfg = load_config()
    daily = _deterministic_bullish_alignment_fixture()
    index_df = pd.DataFrame({"Close": np.linspace(20000, 25000, len(daily))}, index=daily.index)
    regime = compute_market_regime(index_df)
    feats = build_stock_feature_frame(daily, index_df["Close"], regime, cfg)
    assert feats["Any_Entry_Triggered"].sum() > 0, "fixture must guarantee at least one entry trigger"
    return {"DETERMINISTIC": feats}, cfg


def test_same_close_signals_actually_execute(guaranteed_signal_frames):
    frames, cfg = guaranteed_signal_frames
    cfg.execution.model = "same_close"
    cal = NSECalendar()

    n_signals = int(frames["DETERMINISTIC"]["Any_Entry_Triggered"].sum())
    assert n_signals > 0

    result = run_portfolio_backtest(frames, cal, cfg, initial_capital=10_000_000, max_concurrent_positions=1)

    # THE critical assertion this test exists for: same_close signals must
    # produce actual trades, not zero (the bug silently discarded all of them).
    assert len(result.trades) > 0, (
        f"{n_signals} same_close signal(s) were detected but ZERO trades were "
        f"produced -- same_close execution is broken (BLOCKER 3)."
    )

    for t in result.trades:
        assert t.signal_date == t.execution_date, "same_close must execute on the signal date itself"
        feats = frames["DETERMINISTIC"]
        expected_close = float(feats.loc[t.signal_date, "Close"])
        assert t.entry_price == pytest.approx(expected_close), "same_close entry price must equal the signal-day close"


def test_same_close_does_not_leave_orders_permanently_pending(guaranteed_signal_frames):
    """Regression guard for the exact mechanism of the bug: pending_orders
    must never accumulate same_close orders that are never executed."""
    frames, cfg = guaranteed_signal_frames
    cfg.execution.model = "same_close"
    cal = NSECalendar()
    result = run_portfolio_backtest(frames, cal, cfg, initial_capital=10_000_000, max_concurrent_positions=5)
    # pending_orders should be 0 at the end for same_close (nothing should
    # ever have been queued in the first place).
    if not result.equity_curve.empty:
        assert result.equity_curve["pending_orders"].max() == 0
