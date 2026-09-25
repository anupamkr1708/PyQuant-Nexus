"""Weekly no-lookahead tests (brief Section 74 Test D; Section 75; Section 93 #12-13).

Pins BOTH the corrected behavior (Friday can use its own just-closed weekly
candle) AND the invariant that no future data ever leaks into a past date.
See docs/NOTEBOOK_AUDIT.md §3 for why the boundary moved from strict `<` to `<=`.
"""
import pandas as pd

from ema_scanner.features.ema import compute_all_emas
from ema_scanner.features.weekly import (
    attach_last_known_weekly,
    build_true_weekly_ohlc,
    latest_known_weekly_row,
)
from tests.fixtures.synthetic import make_synthetic_ohlcv


def _build(daily):
    d = compute_all_emas(daily)
    weekly = build_true_weekly_ohlc(daily)
    w = compute_all_emas(weekly, suffix="_W")
    return d, w


def test_friday_may_use_its_own_just_closed_weekly_candle():
    daily = make_synthetic_ohlcv(400, seed=40)
    _, w = _build(daily)
    fridays_that_are_weekends = [d for d in w.index if d.weekday() == 4]
    assert fridays_that_are_weekends, "fixture should contain at least one Friday week-end"
    friday = fridays_that_are_weekends[10]
    row = latest_known_weekly_row(w, friday)
    assert row.name == friday  # THE FIX: non-strict <=, Friday sees its own week


def test_thursday_cannot_use_that_same_weeks_candle():
    daily = make_synthetic_ohlcv(400, seed=41)
    _, w = _build(daily)
    fridays = [d for d in w.index if d.weekday() == 4]
    friday = fridays[10]
    thursday_candidates = daily.index[daily.index < friday]
    thursday = thursday_candidates[-1]
    if thursday.weekday() != 3:
        return  # holiday-shifted week; skip rather than assert something not guaranteed
    row = latest_known_weekly_row(w, thursday)
    assert row.name < friday


def test_appending_future_rows_does_not_change_prior_merged_weekly_values():
    """Brief Section 74 Test A/B/D combined."""
    daily_full = make_synthetic_ohlcv(600, seed=42)
    cutoff = daily_full.index[400]
    daily_partial = daily_full.loc[:cutoff]

    d_full, w_full = _build(daily_full)
    merged_full = attach_last_known_weekly(d_full, w_full, ["EMA10_W", "EMA20_W", "EMA89_W", "EMA200_W"])

    d_partial, w_partial = _build(daily_partial)
    merged_partial = attach_last_known_weekly(d_partial, w_partial, ["EMA10_W", "EMA20_W", "EMA89_W", "EMA200_W"])

    check_date = daily_full.index[300]
    cols = ["EMA10_W", "EMA20_W", "EMA89_W", "EMA200_W"]
    a = merged_full.loc[check_date, cols].astype(float)
    b = merged_partial.loc[check_date, cols].astype(float)
    assert (a - b).abs().max() < 1e-9, "appending one month+ of future data changed an older weekly-derived value"


def test_appending_one_month_of_future_data_does_not_alter_older_signals():
    """Brief Section 74 Test B, at the full feature-frame level."""
    from ema_scanner.config import load_config
    from ema_scanner.features.regime import compute_market_regime
    from ema_scanner.strategy.signal_engine import build_stock_feature_frame

    daily_full = make_synthetic_ohlcv(700, seed=43)
    cutoff = daily_full.index[600]  # leaves ~1 month+ of "future" data beyond cutoff
    daily_partial = daily_full.loc[:cutoff]
    index_full = make_synthetic_ohlcv(700, seed=44)[["Close"]]

    cfg = load_config()
    regime_full = compute_market_regime(index_full)
    regime_partial = compute_market_regime(index_full.loc[:cutoff])

    feats_full = build_stock_feature_frame(daily_full, index_full["Close"], regime_full, cfg)
    feats_partial = build_stock_feature_frame(daily_partial, index_full["Close"].loc[:cutoff], regime_partial, cfg)

    check_date = daily_full.index[500]
    compare_cols = ["Daily_State", "Weekly_State", "Cluster_Width_Pct", "Pullback_State", "Signal_State"]
    for col in compare_cols:
        v_full, v_partial = feats_full.loc[check_date, col], feats_partial.loc[check_date, col]
        if pd.isna(v_full) and pd.isna(v_partial):
            continue
        assert v_full == v_partial, f"column {col} at {check_date} changed after appending future data: {v_full!r} vs {v_partial!r}"
