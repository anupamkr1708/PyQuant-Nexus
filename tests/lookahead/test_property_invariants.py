"""Property-based invariant checks (brief Section 94)."""
import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import load_config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_cluster_width_always_nonnegative():
    daily = make_synthetic_ohlcv(400, seed=70)
    index_df = make_synthetic_ohlcv(400, seed=71)[["Close"]]
    cfg = load_config()
    regime = compute_market_regime(index_df)
    feats = build_stock_feature_frame(daily, index_df["Close"], regime, cfg)
    assert (feats["Cluster_Width_Pct"].dropna() >= 0).all()


def test_stop_for_long_never_exceeds_entry_reference_at_entry_points():
    """The invariant (brief Section 94: 'stop for long <= entry reference when
    valid') applies at the moment a trade is actually taken. Swing_Low_Stop
    itself is a rolling diagnostic (last confirmed swing low, forward-filled)
    and CAN legitimately sit above the current Close on days where price has
    since fallen through it without yet printing a new confirmed lower swing
    — that is precisely the condition the backtest engine's stop logic acts
    on (see research/backtest.py's STOP_GAP_THROUGH handling), not a bug."""
    daily = make_synthetic_ohlcv(400, seed=72)
    index_df = make_synthetic_ohlcv(400, seed=73)[["Close"]]
    cfg = load_config()
    regime = compute_market_regime(index_df)
    feats = build_stock_feature_frame(daily, index_df["Close"], regime, cfg)
    at_entry = feats[feats["Any_Entry_Triggered"] & feats["Swing_Low_Stop"].notna()]
    assert (at_entry["Swing_Low_Stop"] <= at_entry["Close"]).all()


def test_next_session_is_always_a_valid_exchange_session():
    cal = NSECalendar()
    for d in pd.bdate_range("2026-01-01", "2026-12-31", freq="7D"):
        nxt = cal.next_session(d)
        if nxt is not None:
            assert cal.is_trading_day(nxt)
