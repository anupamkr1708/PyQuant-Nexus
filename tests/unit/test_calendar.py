"""NSE calendar tests (brief Section 93 #14-16: holiday resolution, weekend
resolution, next trading session)."""
import pandas as pd

from ema_scanner.calendar.nse import NSECalendar


def test_weekend_is_not_a_trading_day():
    cal = NSECalendar()
    assert cal.is_trading_day("2026-09-19") is False  # Saturday
    assert cal.is_trading_day("2026-09-20") is False  # Sunday


def test_known_holiday_is_not_a_trading_day():
    cal = NSECalendar()
    assert cal.is_trading_day("2026-01-26") is False  # Republic Day


def test_next_session_skips_weekend():
    cal = NSECalendar()
    nxt = cal.next_session("2026-09-18")  # Friday
    assert nxt.weekday() == 0  # Monday
    assert nxt == pd.Timestamp("2026-09-21")


def test_previous_session_before_holiday_monday():
    cal = NSECalendar()
    prev = cal.previous_session("2026-01-26")  # Republic Day, Monday
    assert prev.weekday() == 4  # Friday
    assert prev == pd.Timestamp("2026-01-23")


def test_sessions_between_counts_only_trading_days():
    cal = NSECalendar()
    # Friday to Monday: zero trading sessions missed
    n = cal.sessions_between("2026-09-18", "2026-09-21")
    assert n == 0
