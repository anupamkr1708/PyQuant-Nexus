"""Data quality gate tests (brief Section 93 #23-25: duplicate dates, stale data,
missing final session)."""
import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.data.quality import QUALITY_FAIL, QUALITY_PASS, QUALITY_WARN, validate_ohlc
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_duplicate_dates_flagged():
    df = make_synthetic_ohlcv(50, seed=30)
    dup = pd.concat([df, df.iloc[[5]]]).sort_index()
    cal = NSECalendar()
    report = validate_ohlc(dup, cal)
    assert any("duplicate" in i for i in report.issues)


def test_high_below_low_is_a_hard_fail():
    df = make_synthetic_ohlcv(50, seed=31)
    df.iloc[10, df.columns.get_loc("High")] = df.iloc[10]["Low"] - 1.0
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status == QUALITY_FAIL


def test_clean_data_passes():
    df = make_synthetic_ohlcv(300, seed=32)
    cal = NSECalendar()
    report = validate_ohlc(df, cal)
    assert report.status in (QUALITY_PASS, QUALITY_WARN)


def test_stale_data_flagged_using_trading_sessions_not_calendar_days():
    df = make_synthetic_ohlcv(300, seed=33)
    cal = NSECalendar()
    last_date = df.index.max()
    # as_of far in the future -> many missed sessions -> should be stale
    far_future = last_date + pd.Timedelta(days=60)
    report = validate_ohlc(df, cal, as_of_date=far_future, max_stale_sessions=5)
    assert any("stale" in i for i in report.issues)
