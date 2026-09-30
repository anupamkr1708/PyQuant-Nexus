"""Point-in-time analysis-date resolution (brief Section 11; Phase-2 Sections
5, 7 -- both BLOCKER).

Three distinct concepts are now modeled separately (Phase-2 Section 7 --
"do not hard-code 3 PM as the market close" / "separate exchange_session_complete
from provider_data_available from provider_data_final"):

    exchange_session_complete   -- a pure calendar/exchange fact: has the
                                    session's regular close (09:15-15:30 IST
                                    for NSE cash equity) passed?
    eod_data_cutoff_passed      -- an ENGINEERING_DECISION, configurable, later
                                    than the exchange close, representing "is it
                                    now safe to assume an external EOD data
                                    provider has published the final bar?"
                                    Default 16:00 IST -- a buffer, not an
                                    exchange fact. This does NOT model NSE's
                                    closing-auction/post-close mechanics
                                    precisely (see docs/RESEARCH_LIMITATIONS.md);
                                    it exists so a scan doesn't fire the instant
                                    the market closes, when a data vendor may
                                    not have published yet.
    provider_data_final         -- NOT decided by this module at all. Whether
                                    the ACTUAL fetched bar for the resolved date
                                    is present and valid is checked downstream
                                    by the analysis-date data gate (cli.py +
                                    data/quality.py's `eligible_for_signal`),
                                    never assumed here.

Two modes:

- AUTOMATIC: resolve the latest session for which BOTH
  `exchange_session_complete` and `eod_data_cutoff_passed` are true as of "now".
- MANUAL: validate a user-supplied date against three explicit rules
  (Phase-2 Section 5):
    manual_date <  today  -> valid IF it is an actual trading session (data
                              existence is checked later by the data gate)
    manual_date == today  -> valid ONLY if `eod_data_cutoff_passed` for today
    manual_date >  today  -> ALWAYS rejected
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import time as dt_time

import pandas as pd

from ema_scanner.calendar.nse import IST, NSECalendar


class AnalysisDateError(RuntimeError):
    """Raised when a requested date is not usable. Never caught-and-rolled
    silently by callers (Section 11: 'If it is not a trading day, fail clearly
    and tell me why.')."""


DEFAULT_EOD_DATA_CUTOFF = "16:00"  # IST, HH:MM -- see module docstring


@dataclass
class AnalysisDateResolution:
    requested_date: str | None
    resolved_signal_date: pd.Timestamp
    is_trading_day: bool
    exchange_session_complete: bool
    eod_data_cutoff_passed: bool
    is_session_complete: bool  # kept for backward compat: == exchange_session_complete
    session_open: pd.Timestamp
    session_close: pd.Timestamp
    eod_data_cutoff_timestamp: pd.Timestamp
    calendar_source: str
    calendar_version: str
    mode: str  # "AUTOMATIC" | "MANUAL"
    reason: str


def _now_ist(now: datetime | None) -> pd.Timestamp:
    if now is None:
        return pd.Timestamp.now(tz=IST)
    ts = pd.Timestamp(now)
    return ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)


def _cutoff_timestamp(date: pd.Timestamp, cutoff_time: str) -> pd.Timestamp:
    h, m = (int(x) for x in cutoff_time.split(":"))
    return pd.Timestamp.combine(date.date(), dt_time(h, m)).tz_localize(IST)


def resolve_analysis_date(
    calendar: NSECalendar,
    *,
    manual_date: str | None = None,
    now: datetime | None = None,
    eod_data_cutoff: str = DEFAULT_EOD_DATA_CUTOFF,
) -> AnalysisDateResolution:
    now_ts = _now_ist(now)
    today = now_ts.normalize()

    if manual_date is not None:
        d = pd.Timestamp(manual_date).normalize()
        today_naive = today.tz_localize(None)
        info = calendar.session_info(d)
        cutoff_ts = _cutoff_timestamp(d, eod_data_cutoff)

        if d.date() > today_naive.date():
            raise AnalysisDateError(
                f"{manual_date} is in the future (today is {today.date()}). "
                f"A future date can never be a completed EOD session -- rejected unconditionally."
            )
        if not info.is_trading_day:
            raise AnalysisDateError(
                f"{manual_date} is not an NSE cash-equity trading session "
                f"(weekend or exchange holiday). Refusing to silently roll to another "
                f"date -- pass an actual trading date."
            )
        if info.session_close is None and d.date() == today_naive.date():
            raise AnalysisDateError(
                f"{manual_date} is today's session and is a special session whose exact timing is not "
                f"verified in the calendar reference data (see configs/nse_special_sessions.yaml). "
                f"Completion cannot be determined without inferring a time, which this system refuses "
                f"to do -- request this date again once the session's date has fully passed."
            )
        if d.date() == today_naive.date() and now_ts < cutoff_ts:
            raise AnalysisDateError(
                f"{manual_date} is today's session and it has not yet reached the "
                f"configured EOD data cutoff ({eod_data_cutoff} IST; now is "
                f"{now_ts.strftime('%H:%M')} IST). The session may still be trading or "
                f"the EOD data provider may not have published the final bar yet -- "
                f"refusing to treat today as complete. Try again after {eod_data_cutoff} IST, "
                f"or request yesterday's session."
            )
        # A session with unverified timing (e.g. Muhurat) is treated as complete
        # only because its calendar DATE is strictly in the past (guaranteed by
        # the two checks above) -- never via an inferred clock time.
        exchange_complete = now_ts >= info.session_close if info.session_close is not None else True
        cutoff_passed = now_ts >= cutoff_ts
        return AnalysisDateResolution(
            requested_date=manual_date, resolved_signal_date=d, is_trading_day=True,
            exchange_session_complete=exchange_complete, eod_data_cutoff_passed=cutoff_passed,
            is_session_complete=exchange_complete,
            session_open=info.session_open, session_close=info.session_close,
            eod_data_cutoff_timestamp=cutoff_ts,
            calendar_source=calendar.calendar_source, calendar_version=calendar.calendar_version,
            mode="MANUAL",
            reason=(
                "manual historical scan of an explicitly requested, validated trading session"
                if d.date() < today_naive.date() else
                f"manual scan of today's session, accepted because now ({now_ts.strftime('%H:%M')} IST) "
                f"is past the configured EOD data cutoff ({eod_data_cutoff} IST)"
            ),
        )

    # AUTOMATIC mode: search backward (bounded) for the latest session for which
    # BOTH the exchange close AND the (later, configurable) EOD data cutoff have passed.
    cursor = today
    for _ in range(30):
        info = calendar.session_info(cursor)
        if info.is_trading_day and info.session_close is None:
            # Known trading DATE, unknown TIMING (Phase-3 BLOCKER 8): complete
            # only once the calendar date has fully passed -- no time is inferred.
            cutoff_ts = _cutoff_timestamp(cursor, eod_data_cutoff)
            if cursor.date() < today.date():
                return AnalysisDateResolution(
                    requested_date=None, resolved_signal_date=cursor.tz_localize(None),
                    is_trading_day=True, exchange_session_complete=True, eod_data_cutoff_passed=True,
                    is_session_complete=True, session_open=info.session_open, session_close=info.session_close,
                    eod_data_cutoff_timestamp=cutoff_ts, calendar_source=calendar.calendar_source,
                    calendar_version=calendar.calendar_version, mode="AUTOMATIC",
                    reason=(
                        "latest session is a special session with unverified timing; treated as complete "
                        "only because its calendar date has fully passed (no time inferred)"
                    ),
                )
        elif info.is_trading_day and info.session_close is not None:
            cutoff_ts = _cutoff_timestamp(cursor, eod_data_cutoff)
            exchange_complete = now_ts >= info.session_close
            cutoff_passed = now_ts >= cutoff_ts
            if exchange_complete and cutoff_passed:
                return AnalysisDateResolution(
                    requested_date=None, resolved_signal_date=cursor.tz_localize(None),
                    is_trading_day=True, exchange_session_complete=True, eod_data_cutoff_passed=True,
                    is_session_complete=True,
                    session_open=info.session_open, session_close=info.session_close,
                    eod_data_cutoff_timestamp=cutoff_ts,
                    calendar_source=calendar.calendar_source, calendar_version=calendar.calendar_version,
                    mode="AUTOMATIC",
                    reason=(
                        f"latest NSE cash-equity session whose close AND configured EOD data "
                        f"cutoff ({eod_data_cutoff} IST) have both passed, as of "
                        f"{now_ts.isoformat()} IST"
                    ),
                )
        cursor = cursor - pd.Timedelta(days=1)
    raise AnalysisDateError(
        f"Could not resolve a completed NSE session within 30 days back from {now_ts}. "
        f"This almost certainly indicates a calendar-provider problem, not an actual "
        f"30-day market closure -- investigate before proceeding."
    )
