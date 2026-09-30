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
   model consistently — see DATA_SOURCES.md). By default this is populated from
   `configs/nse_special_sessions.yaml` (calendar/reference.py) -- an explicit,
   auditable data file, never a silently-guessed date. That file records the
   2026 Muhurat Trading DATE (per secondary sources citing NSE's own 2026
   holiday list) with its exact TIMING deliberately left unverified/null
   (Phase-3 BLOCKER 8) -- see that file's own comments for the citation trail.
2. `validate_against(reference_holidays)` lets the calendar be checked against an
   authoritative NSE holiday list fetched at runtime, rather than trusted blindly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

from ema_scanner.calendar.reference import CalendarReferenceEntry, load_reference_entries

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
    load_default_reference: bool = True
    reference_entries: list[CalendarReferenceEntry] = field(default_factory=list)
    _cal: mcal.MarketCalendar = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cal = mcal.get_calendar(self.calendar_name)
        if self.load_default_reference:
            self.apply_reference_entries(load_reference_entries())

    @property
    def calendar_version(self) -> str:
        """Library version PLUS the special-session reference-data version, so a
        run manifest identifies exactly which calendar data was in force."""
        import pandas_market_calendars as _m

        ref_version = self.reference_entries[0].calendar_version if self.reference_entries else "no_reference_data"
        return f"{_m.__version__}+{ref_version}"

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
        """All trading-day DATES (tz-naive, normalized) in [start, end], honoring overrides.

        Phase-3 fix: override dates are filtered to the REQUESTED range. The
        earlier version added every override date regardless of `start`/`end`
        -- harmless while the override table was empty, but it would have
        injected e.g. a Nov-2026 Muhurat session into any query about another
        year the moment a real special session was registered."""
        start_ts, end_ts = pd.Timestamp(start).tz_localize(None).normalize(), pd.Timestamp(end).tz_localize(None).normalize()
        base = self._cal.valid_days(start_date=start_ts, end_date=end_ts)
        base = pd.DatetimeIndex([pd.Timestamp(d).tz_localize(None).normalize() for d in base])
        in_range = {
            pd.Timestamp(k).normalize(): v for k, v in self.special_session_overrides.items()
            if start_ts <= pd.Timestamp(k).normalize() <= end_ts
        }
        removed = {d for d, v in in_range.items() if not v.is_trading_day}
        added = {d for d, v in in_range.items() if v.is_trading_day}
        out = (set(base) - removed) | added
        return pd.DatetimeIndex(sorted(out))

    def expected_week_ends(self, start, end) -> pd.Series:
        """Phase-3 BLOCKER 8: for every ISO week touching [start, end], the
        LAST SCHEDULED session date that week per THIS calendar (including
        registered special sessions such as a Sunday Muhurat session).
        Indexed by ISO week label ('YYYY-Www'). The window is extended
        forward to the end of the last ISO week so a still-forming final
        week gets its true scheduled boundary rather than 'whatever bar
        happens to be present so far'."""
        start_ts, end_ts = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        week_end_of_range = end_ts + pd.Timedelta(days=6 - end_ts.weekday())
        sessions = self.valid_sessions(start_ts - pd.Timedelta(days=start_ts.weekday()), week_end_of_range)
        iso = sessions.isocalendar()
        labels = pd.Series([f"{y:04d}-W{w:02d}" for y, w in zip(iso["year"], iso["week"])], index=sessions)
        return labels.groupby(labels).apply(lambda g: g.index.max()).rename("ExpectedWeekEnd")

    def apply_reference_entries(self, entries: list[CalendarReferenceEntry]) -> None:
        """Registers reference entries as overrides. A trading-day entry whose
        timing is unverified gets `session_open/close=None` -- the calendar
        knows a session happens that day but NOT when; nothing downstream may
        treat such a session as completed via a clock comparison."""
        for e in entries:
            if e.is_trading_day:
                def _ts(hhmm: str | None, _e=e):
                    if hhmm is None:
                        return None
                    h, m = (int(x) for x in hhmm.split(":"))
                    return pd.Timestamp.combine(pd.Timestamp(_e.date).date(), time(h, m)).tz_localize(IST)
                self.special_session_overrides[e.date] = SessionInfo(
                    date=pd.Timestamp(e.date), is_trading_day=True, session_open=_ts(e.session_open),
                    session_close=_ts(e.session_close), is_special_session=True,
                    note=f"{e.session_type}; timing_verified={e.timing_verified}; source={e.source_url or e.source}",
                )
            else:
                self.special_session_overrides[e.date] = SessionInfo(
                    date=pd.Timestamp(e.date), is_trading_day=False, session_open=None, session_close=None,
                    is_special_session=False, note=f"HOLIDAY override; source={e.source_url or e.source}",
                )
        self.reference_entries = list(entries)

    def has_verified_timing(self, date) -> bool:
        """True only if this date's open/close are actually known."""
        info = self.session_info(date)
        return info.is_trading_day and info.session_open is not None and info.session_close is not None

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
