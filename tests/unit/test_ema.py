"""EMA engine tests (brief Section 93 #1: EMA reference; Section 3: short
series, exact seed point, constant series, monotonic series, random series,
NaN handling, multiple periods)."""
import numpy as np
import pandas as pd
import pytest

from ema_scanner.features.ema import compute_ema, reference_ema_pandas_adjust_false
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_ema_matches_trusted_reference_after_seed():
    df = make_synthetic_ohlcv(300, seed=1)
    for period in (10, 20, 89, 200):
        mine = compute_ema(df["Close"], period, seed_method="sma")
        ref = reference_ema_pandas_adjust_false(df["Close"], period)
        diff = (mine - ref).abs().dropna()
        assert diff.max() < 1e-8, f"EMA period={period} diverges from trusted pandas reference by {diff.max()}"


def test_ema_seed_point_is_sma_of_first_n():
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    period = 5
    ema = compute_ema(s, period, seed_method="sma")
    assert np.isnan(ema.iloc[: period - 1]).all()
    assert ema.iloc[period - 1] == pytest.approx(s.iloc[:period].mean())


def test_ema_constant_series_equals_the_constant():
    s = pd.Series([42.0] * 50)
    ema = compute_ema(s, 10)
    assert (ema.dropna() == 42.0).all()


def test_ema_monotonic_series_stays_monotonic_after_seed():
    s = pd.Series(np.arange(1, 101, dtype=float))
    ema = compute_ema(s, 10).dropna()
    assert (ema.diff().dropna() > 0).all()


def test_ema_short_series_returns_all_nan():
    s = pd.Series([1.0, 2.0, 3.0])
    ema = compute_ema(s, 10)
    assert ema.isna().all()


def test_ema_multiple_periods_independent():
    df = make_synthetic_ohlcv(400, seed=2)
    e10 = compute_ema(df["Close"], 10)
    e200 = compute_ema(df["Close"], 200)
    assert e10.notna().sum() > e200.notna().sum()  # shorter period seeds earlier


def test_ema_first_obs_seed_method_starts_at_bar_zero():
    s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    ema = compute_ema(s, 3, seed_method="first_obs")
    assert ema.iloc[0] == 10.0
    assert ema.notna().all()


def test_ema_rejects_unknown_seed_method():
    s = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        compute_ema(s, 2, seed_method="bogus")


def test_ema_rejects_nonpositive_period():
    s = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        compute_ema(s, 0)
