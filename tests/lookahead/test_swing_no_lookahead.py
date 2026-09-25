"""Swing no-lookahead tests (brief Section 74 Test C, Section 94 invariants)."""
import pandas as pd

from ema_scanner.features.swing import detect_swing_points, vectorized_last_confirmed_swing_low
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_confirmed_swing_timestamps_never_earlier_than_swing_timestamps():
    df = make_synthetic_ohlcv(300, seed=50)
    swing = detect_swing_points(df, left=5, right=5)
    lows = swing[swing["Is_Swing_Low"]]
    assert (lows["Swing_Low_Confirmed_At"] >= lows.index).all()


def test_adding_a_later_swing_does_not_change_an_earlier_confirmed_value():
    daily_full = make_synthetic_ohlcv(400, seed=51)
    cutoff = daily_full.index[250]
    daily_partial = daily_full.loc[:cutoff]

    swing_full = detect_swing_points(daily_full, left=5, right=5)
    swing_partial = detect_swing_points(daily_partial, left=5, right=5)

    vec_full = vectorized_last_confirmed_swing_low(swing_full)
    vec_partial = vectorized_last_confirmed_swing_low(swing_partial)

    check_date = daily_full.index[200]
    a, b = vec_full.loc[check_date], vec_partial.loc[check_date]
    if pd.isna(a) and pd.isna(b):
        return
    assert a == b, f"adding a later swing changed the confirmed swing-low value at {check_date}"
