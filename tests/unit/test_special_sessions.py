"""BLOCKER 8 (Phase-3): special-session calendar reference data.

Distinguishes a known trading DATE from known exact session TIMING, and never
infers an unverified time.
"""
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.calendar.reference import (
    CalendarReferenceEntry,
    CalendarReferenceError,
    load_reference_entries,
)
from ema_scanner.calendar.sessions import AnalysisDateError, resolve_analysis_date

IST = ZoneInfo("Asia/Kolkata")


def _entry(**kw):
    base = {
        "date": "2030-01-01", "is_trading_day": True, "session_type": "SPECIAL", "session_open": None,
        "session_close": None, "timing_verified": False, "source": "test", "source_url": None,
        "verified_at": None, "official_document_verified": False, "calendar_version": "test_v1",
    }
    base.update(kw)
    return CalendarReferenceEntry(**base)


def test_unverified_timing_with_times_supplied_is_rejected():
    with pytest.raises(CalendarReferenceError, match="unverified"):
        _entry(session_open="18:15", session_close="19:15", timing_verified=False).validate()


def test_verified_timing_requires_both_times():
    with pytest.raises(CalendarReferenceError):
        _entry(session_open="18:15", session_close=None, timing_verified=True).validate()
    _entry(session_open="18:15", session_close="19:15", timing_verified=True).validate()  # ok


def test_non_trading_entry_must_be_a_holiday_type():
    with pytest.raises(CalendarReferenceError):
        _entry(is_trading_day=False, session_type="MUHURAT").validate()


def test_default_reference_contains_muhurat_2026_date_but_no_invented_timing():
    entries = {e.date: e for e in load_reference_entries()}
    e = entries["2026-11-08"]
    assert e.is_trading_day is True and e.session_type == "MUHURAT"
    assert e.session_open is None and e.session_close is None, "timing must not be invented"
    assert e.timing_verified is False
    assert e.official_document_verified is False, "the primary NSE document was not inspected; must say so"


def test_calendar_knows_the_date_but_not_the_timing():
    cal = NSECalendar()
    assert cal.is_trading_day("2026-11-08") is True          # known trading date (a Sunday)
    assert cal.has_verified_timing("2026-11-08") is False     # timing NOT known
    assert cal.has_verified_timing("2026-09-22") is True      # ordinary session: timing known


def test_override_dates_outside_requested_range_are_not_injected():
    """Regression for the valid_sessions range bug found while adding this."""
    cal = NSECalendar()
    assert pd.Timestamp("2026-11-08") not in cal.valid_sessions("2024-01-01", "2024-12-31")
    assert pd.Timestamp("2026-11-08") in cal.valid_sessions("2026-11-01", "2026-11-30")


def test_calendar_version_identifies_reference_data():
    assert "nse_special_sessions_v1" in NSECalendar().calendar_version
    assert "no_reference_data" in NSECalendar(load_default_reference=False).calendar_version


def test_manual_today_special_session_with_unknown_timing_is_rejected():
    cal = NSECalendar()
    now = pd.Timestamp("2026-11-08 19:00", tz=IST)  # the Muhurat Sunday itself
    with pytest.raises(AnalysisDateError, match="timing is not verified"):
        resolve_analysis_date(cal, manual_date="2026-11-08", now=now)


def test_manual_past_special_session_is_accepted_without_inferring_a_time():
    cal = NSECalendar()
    now = pd.Timestamp("2026-11-09 18:00", tz=IST)
    res = resolve_analysis_date(cal, manual_date="2026-11-08", now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-11-08")
    assert res.session_close is None  # still unknown -- not fabricated


def test_automatic_mode_on_the_special_session_day_does_not_resolve_to_it():
    cal = NSECalendar()
    now = pd.Timestamp("2026-11-08 20:00", tz=IST)  # Sunday evening, session date not yet passed
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-11-06")  # last Friday, NOT the unverifiable Sunday


def test_automatic_mode_after_the_special_session_date_resolves_to_it_without_inferring_time():
    cal = NSECalendar()
    now = pd.Timestamp("2026-11-09 10:00", tz=IST)  # Monday morning, Monday's own session not complete
    res = resolve_analysis_date(cal, now=now)
    assert res.resolved_signal_date == pd.Timestamp("2026-11-08")
    assert "no time inferred" in res.reason
