"""Point-in-time analysis-date tests (brief Section 93 #15-16, Section 11)."""
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.calendar.sessions import AnalysisDateError, resolve_analysis_date

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="module")
def cal():
    return NSECalendar()


def test_automatic_after_close_uses_today(cal):
    now = pd.Timestamp("2026-09-22 18:15", tz=IST)  # Tuesday, after 15:30 close
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-09-22")


def test_automatic_before_close_uses_previous_session(cal):
    now = pd.Timestamp("2026-09-22 10:00", tz=IST)  # Tuesday, before close
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-09-21")


def test_automatic_on_weekend_rolls_back_to_friday(cal):
    now = pd.Timestamp("2026-09-26 12:00", tz=IST)  # Saturday
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date.weekday() == 4


def test_manual_mode_rejects_non_trading_day(cal):
    with pytest.raises(AnalysisDateError):
        resolve_analysis_date(cal, manual_date="2026-09-19")  # Saturday


def test_manual_mode_never_rolls_to_another_date(cal):
    res = resolve_analysis_date(cal, manual_date="2026-09-21")
    assert res.resolved_signal_date == pd.Timestamp("2026-09-21")
    assert res.mode == "MANUAL"
