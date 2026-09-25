"""NSE cash-equity trading calendar (Section 10 of the refactor brief).

Backed by `pandas_market_calendars`'s `XNSE` calendar (verified real, installable
from PyPI — see docs/DATA_SOURCES.md for how/when this was checked). Cash-equity
regular session hours (09:15-15:30 IST) were independently confirmed by web search
against NSE's own published trading-hours pages on 2026-09-22; see the same file.

CRITICAL per the brief: "A packaged calendar library may be used as a helper, but
it must not become an unquestioned permanent source of truth." Two things follow:

1. `special_session_overrides` lets a caller inject/remove sessions the library gets
   wrong (e.g. Muhurat Trading, which is a short evening session on a date that is
   otherwise a Saturday/Sunday holiday and which vendor calendars do not always
   model consistently — see DATA_SOURCES.md). This system does NOT silently invent
   Muhurat dates; the override list starts empty and must be populated from an
   official NSE circular by the operator.
2. `validate_against(reference_holidays)` lets the calendar be checked against an
   authoritative NSE holiday list fetched at runtime, rather than trusted blindly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class SessionInfo:
    date: pd.Timestamp
    is_trading_day: bool
    session_open: pd.Timestamp | None
    session_close: pd.Timestamp | None
    is_special_session: bool = False
    note: str | None = None


@dataclass
class NSECalendar:
    """Wraps the XNSE calendar. `calendar_source`/`calendar_version` are recorded
    into every run manifest (Section 61) so a research run is reproducible even if
    the underlying calendar library is later updated."""

    calendar_name: str = "XNSE"
    calendar_source: str = "pandas_market_calendars"
    special_session_overrides: dict[str, SessionInfo] = field(default_factory=dict)
    _cal: mcal.MarketCalendar = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cal = mcal.get_calendar(self.calendar_name)

    @property
    def calendar_version(self) -> str:
        import pandas_market_calendars as _m

        return _m.__version__

    def schedule(self, start: str, end: str) -> pd.DataFrame:
        """Raw open/close schedule (tz-aware, converted to IST) for [start, end].
        Returns an empty (but correctly-typed) frame when there are no sessions in
        range, e.g. a single non-trading day."""
        sched = self._cal.schedule(start_date=start, end_date=end)
        if sched.empty:
            return sched
        for col in ("market_open", "market_close"):
            if sched[col].dt.tz is None:
                sched[col] = sched[col].dt.tz_localize("UTC").dt.tz_convert(IST)
            else:
                sched[col] = sched[col].dt.tz_convert(IST)
        return sched

    def is_trading_day(self, date) -> bool:
        d = pd.Timestamp(date).normalize()
        key = d.date().isoformat()
        if key in self.special_session_overrides:
            return self.special_session_overrides[key].is_trading_day
        valid = self._cal.valid_days(start_date=d, end_date=d)
        return len(valid) > 0

    def session_info(self, date) -> SessionInfo:
        d = pd.Timestamp(date).normalize()
        key = d.date().isoformat()
        if key in self.special_session_overrides:
            return self.special_session_overrides[key]
        sched = self.schedule(d.date().isoformat(), d.date().isoformat())
        if sched.empty:
            return SessionInfo(date=d, is_trading_day=False, session_open=None, session_close=None)
        row = sched.iloc[0]
        return SessionInfo(
            date=d,
            is_trading_day=True,
            session_open=row["market_open"],
            session_close=row["market_close"],
        )

    def valid_sessions(self, start, end) -> pd.DatetimeIndex:
        """All trading-day DATES (tz-naive, normalized) in [start, end], honoring overrides."""
        base = self._cal.valid_days(start_date=start, end_date=end)
        base = pd.DatetimeIndex([pd.Timestamp(d).tz_localize(None).normalize() for d in base])
        removed = {
            pd.Timestamp(k).normalize()
            for k, v in self.special_session_overrides.items()
            if not v.is_trading_day
        }
        added = {
            pd.Timestamp(k).normalize()
            for k, v in self.special_session_overrides.items()
            if v.is_trading_day
        }
        out = (set(base) - removed) | added
        return pd.DatetimeIndex(sorted(out))

    def next_session(self, date) -> pd.Timestamp | None:
        d = pd.Timestamp(date).normalize()
        window = self.valid_sessions(d + pd.Timedelta(days=1), d + pd.Timedelta(days=30))
        return window[0] if len(window) else None

    def previous_session(self, date) -> pd.Timestamp | None:
        d = pd.Timestamp(date).normalize()
        window = self.valid_sessions(d - pd.Timedelta(days=30), d - pd.Timedelta(days=1))
        return window[-1] if len(window) else None

    def sessions_between(self, start, end) -> int:
        """Count of trading sessions strictly between two dates (for staleness checks)."""
        return len(self.valid_sessions(pd.Timestamp(start) + pd.Timedelta(days=1),
                                        pd.Timestamp(end) - pd.Timedelta(days=1)))

    def trading_week_id(self, dates: pd.DatetimeIndex) -> pd.Series:
        """Assigns each date its (ISO year, ISO week) label. Used by features/weekly.py to
        group daily bars into weeks by ACTUAL trading calendar, not a fixed `W-FRI` anchor
        (brief Section 9: a fixed weekday anchor can misclassify holiday-shortened weeks and
        special Saturday/Sunday sessions)."""
        iso = pd.Index(dates).isocalendar()
        return pd.Series(
            [f"{y:04d}-W{w:02d}" for y, w in zip(iso["year"], iso["week"])], index=dates
        )

    def validate_against(self, reference_holiday_dates: set[str]) -> dict:
        """Compares this calendar's non-trading weekdays in the span of
        `reference_holiday_dates` against an externally supplied authoritative list
        (e.g. scraped from nseindia.com's official holiday page at runtime). Returns
        a diff rather than raising, so a caller can decide how to treat mismatches;
        never silently trusts the packaged library over an authoritative source."""
        if not reference_holiday_dates:
            return {"checked": 0, "matched": 0, "missing_in_library": [], "extra_in_library": []}
        ref = {pd.Timestamp(d).normalize() for d in reference_holiday_dates}
        start, end = min(ref), max(ref)
        weekdays = pd.bdate_range(start, end)
        lib_holidays = {d for d in weekdays if not self.is_trading_day(d)}
        return {
            "checked": len(ref),
            "matched": len(ref & lib_holidays),
            "missing_in_library": sorted(str(d.date()) for d in (ref - lib_holidays)),
            "extra_in_library": sorted(str(d.date()) for d in (lib_holidays - ref)),
        }
