"""Brief Section 74 Test G: manual historical scan must produce identical
results whether or not future data exists locally."""
import pandas as pd

from ema_scanner.config import load_config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_manual_date_scan_is_identical_with_or_without_future_rows():
    daily_full = make_synthetic_ohlcv(500, seed=60)
    manual_date = daily_full.index[350]
    daily_with_future = daily_full  # includes rows after manual_date
    daily_without_future = daily_full.loc[:manual_date]  # trimmed at manual_date

    index_full = make_synthetic_ohlcv(500, seed=61)[["Close"]]
    cfg = load_config()

    regime_with = compute_market_regime(index_full)
    regime_without = compute_market_regime(index_full.loc[:manual_date])

    feats_with = build_stock_feature_frame(daily_with_future, index_full["Close"], regime_with, cfg)
    feats_without = build_stock_feature_frame(daily_without_future, index_full["Close"].loc[:manual_date], regime_without, cfg)

    row_with = feats_with.loc[manual_date]
    row_without = feats_without.loc[manual_date]
    for col in ["Daily_State", "Weekly_State", "Signal_State", "Cluster_Width_Pct", "ATR14", "Swing_Low_Stop"]:
        a, b = row_with[col], row_without[col]
        if pd.isna(a) and pd.isna(b):
            continue
        assert a == b, f"column {col} differs between with/without future data at manual_date: {a!r} vs {b!r}"
