"""Point-in-time analysis-date tests (brief Section 11; Phase-2 Sections 5, 7, 31).

Covers the required Phase-2 acceptance cases: today-before-EOD rejection,
today-after-EOD acceptance, yesterday, future-date rejection, holiday, weekend.
"""
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.calendar.sessions import AnalysisDateError, resolve_analysis_date

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="module")
def cal():
    return NSECalendar()


# --- AUTOMATIC mode ---

def test_automatic_after_cutoff_uses_today(cal):
    now = pd.Timestamp("2026-09-22 18:15", tz=IST)  # Tuesday, well past 16:00 cutoff
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-09-22")
    assert res.exchange_session_complete is True
    assert res.eod_data_cutoff_passed is True


def test_automatic_after_close_but_before_cutoff_uses_previous_session(cal):
    """15:45 IST: exchange session IS closed (15:30), but the configured EOD
    data cutoff (16:00) has not passed yet -- must NOT use today."""
    now = pd.Timestamp("2026-09-22 15:45", tz=IST)  # Tuesday
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-09-21")


def test_automatic_before_close_uses_previous_session(cal):
    now = pd.Timestamp("2026-09-22 10:00", tz=IST)  # Tuesday, before close
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-09-21")


def test_automatic_on_weekend_rolls_back_to_friday(cal):
    now = pd.Timestamp("2026-09-26 12:00", tz=IST)  # Saturday
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date.weekday() == 4


# --- MANUAL mode: the three required rules (Phase-2 Section 5) ---

def test_manual_yesterday_is_accepted(cal):
    now = pd.Timestamp("2026-09-22 10:00", tz=IST)  # "today" = Tuesday 22nd
    res = resolve_analysis_date(cal, manual_date="2026-09-21", now=now)  # Monday
    assert res.resolved_signal_date == pd.Timestamp("2026-09-21")
    assert res.mode == "MANUAL"


def test_manual_today_before_cutoff_is_rejected(cal):
    now = pd.Timestamp("2026-09-22 14:00", tz=IST)  # Tuesday, before 16:00 cutoff
    with pytest.raises(AnalysisDateError, match="not yet reached the configured EOD data cutoff"):
        resolve_analysis_date(cal, manual_date="2026-09-22", now=now)


def test_manual_today_after_cutoff_is_accepted(cal):
    now = pd.Timestamp("2026-09-22 18:00", tz=IST)  # Tuesday, after 16:00 cutoff
    res = resolve_analysis_date(cal, manual_date="2026-09-22", now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-09-22")
    assert res.eod_data_cutoff_passed is True


def test_manual_future_date_is_always_rejected(cal):
    now = pd.Timestamp("2026-09-22 18:00", tz=IST)
    with pytest.raises(AnalysisDateError, match="in the future"):
        resolve_analysis_date(cal, manual_date="2026-09-23", now=now)


def test_manual_mode_rejects_weekend(cal):
    now = pd.Timestamp("2026-09-22 18:00", tz=IST)
    with pytest.raises(AnalysisDateError):
        resolve_analysis_date(cal, manual_date="2026-09-19", now=now)  # Saturday


def test_manual_mode_rejects_holiday(cal):
    now = pd.Timestamp("2026-02-01 18:00", tz=IST)
    with pytest.raises(AnalysisDateError):
        resolve_analysis_date(cal, manual_date="2026-01-26", now=now)  # Republic Day


def test_manual_mode_never_rolls_to_another_date(cal):
    now = pd.Timestamp("2026-09-22 18:00", tz=IST)
    res = resolve_analysis_date(cal, manual_date="2026-09-21", now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-09-21")
    assert res.mode == "MANUAL"


def test_custom_eod_cutoff_is_honored(cal):
    """A stricter (later) cutoff should reject a time that the default would accept."""
    now = pd.Timestamp("2026-09-22 16:30", tz=IST)
    # default cutoff (16:00) would accept this as today
    res_default = resolve_analysis_date(cal, manual_date="2026-09-22", now=now)
    assert res_default.resolved_signal_date == pd.Timestamp("2026-09-22")
    # a stricter 17:00 cutoff must reject the same moment
    with pytest.raises(AnalysisDateError):
        resolve_analysis_date(cal, manual_date="2026-09-22", now=now, eod_data_cutoff="17:00")
