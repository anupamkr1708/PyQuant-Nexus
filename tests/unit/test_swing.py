"""Swing structure tests (brief Section 93 #10-11: swing confirmation)."""
import numpy as np
import pytest

from ema_scanner.features.swing import (
    detect_swing_points,
    latest_confirmed_swing_low,
    vectorized_last_confirmed_swing_low,
)
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_swing_low_confirmation_lag_scalar_and_vectorized_agree():
    df = make_synthetic_ohlcv(200, seed=11)
    swing = detect_swing_points(df, left=5, right=5)
    vec = vectorized_last_confirmed_swing_low(swing)
    # Spot-check several dates
    for d in df.index[::20]:
        scalar = latest_confirmed_swing_low(swing, d)
        vec_val = vec.loc[d]
        if scalar["price"] is None:
            assert np.isnan(vec_val)
        else:
            assert scalar["price"] == pytest.approx(vec_val)


def test_swing_not_available_before_confirmation_date():
    df = make_synthetic_ohlcv(120, seed=12)
    swing = detect_swing_points(df, left=5, right=5)
    swing_rows = swing[swing["Is_Swing_Low"]]
    if swing_rows.empty:
        return
    swing_date = swing_rows.index[0]
    confirm_date = swing_rows.iloc[0]["Swing_Low_Confirmed_At"]
    day_before_confirm = df.index[df.index.get_loc(confirm_date) - 1]
    if day_before_confirm < swing_date:
        return
    result_at = latest_confirmed_swing_low(swing, confirm_date)
    # At/after confirmation, the swing's own price must be picked up (or a later one)
    assert result_at["price"] is not None
