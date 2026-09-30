"""BLOCKER 9/10 (Phase-3): non-finite OHLCV rejection and index contract."""
import numpy as np
import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.data.quality import QUALITY_FAIL, validate_ohlc
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_nan_in_close_is_hard_fail():
    df = make_synthetic_ohlcv(50, seed=60)
    df.iloc[10, df.columns.get_loc("Close")] = np.nan
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status == QUALITY_FAIL
    assert report.eligible_for_signal is False
    assert any("non-finite" in i for i in report.issues)


def test_positive_infinity_in_high_is_hard_fail():
    df = make_synthetic_ohlcv(50, seed=61)
    df.iloc[5, df.columns.get_loc("High")] = np.inf
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status == QUALITY_FAIL


def test_negative_infinity_in_volume_is_hard_fail():
    df = make_synthetic_ohlcv(50, seed=62)
    df["Volume"] = df["Volume"].astype(float)
    df.iloc[5, df.columns.get_loc("Volume")] = -np.inf
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status == QUALITY_FAIL


def test_non_datetimeindex_is_hard_fail():
    df = make_synthetic_ohlcv(20, seed=63)
    df = df.reset_index(drop=True)  # RangeIndex, not DatetimeIndex
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status == QUALITY_FAIL
    assert any("DatetimeIndex" in i for i in report.issues)


def test_timezone_aware_index_is_hard_fail():
    df = make_synthetic_ohlcv(20, seed=64)
    df.index = df.index.tz_localize("UTC")
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status == QUALITY_FAIL
    assert any("timezone-aware" in i for i in report.issues)


def test_non_midnight_timestamps_are_hard_fail():
    df = make_synthetic_ohlcv(20, seed=65)
    df.index = df.index + pd.Timedelta(hours=9, minutes=15)  # e.g. accidental session-open timestamp
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status == QUALITY_FAIL
    assert any("non-midnight" in i for i in report.issues)


def test_clean_data_still_passes_all_new_checks():
    df = make_synthetic_ohlcv(300, seed=66)
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status != QUALITY_FAIL
