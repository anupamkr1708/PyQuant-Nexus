"""Point-in-time analysis-date resolution (Section 11 of the refactor brief).

This is the module that replaces the notebook's implicit `pd.Timestamp.today()` /
`feats.index.max()` behavior (see docs/NOTEBOOK_AUDIT.md §4). Two modes:

- AUTOMATIC: resolve the latest COMPLETED NSE cash-equity session as of "now".
- MANUAL: validate a user-supplied date is an actual completed trading session and
  use exactly that, never silently rolling to another date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from ema_scanner.calendar.nse import IST, NSECalendar


class AnalysisDateError(RuntimeError):
    """Raised when a manually requested date is not usable. Never caught-and-rolled
    silently by callers (Section 11: 'If it is not a trading day, fail clearly and
    tell me why.')."""


@dataclass
class AnalysisDateResolution:
    requested_date: str | None
    resolved_signal_date: pd.Timestamp
    is_trading_day: bool
    is_session_complete: bool
    session_open: pd.Timestamp
    session_close: pd.Timestamp
    calendar_source: str
    calendar_version: str
    mode: str  # "AUTOMATIC" | "MANUAL"
    reason: str


def resolve_analysis_date(
    calendar: NSECalendar,
    *,
    manual_date: str | None = None,
    now: datetime | None = None,
) -> AnalysisDateResolution:
    """AUTOMATIC mode (manual_date is None): walk backward from `now` (IST) to find
    the latest session whose close has already passed. Never returns today's session
    if it hasn't closed yet, and never guesses using `date - 1 day` arithmetic.

    MANUAL mode (manual_date given, e.g. "2026-09-21"): the date must be an actual
    completed NSE trading session; otherwise raises AnalysisDateError. Manual mode
    never uses data later than the manual date's own close, by construction of the
    caller's data-loading code (see data/base.py's `as_of` parameter).
    """
    now_ts: pd.Timestamp
    if now is None:
        now_ts = pd.Timestamp.now(tz=IST)
    else:
        now_ts = pd.Timestamp(now)
        now_ts = now_ts.tz_localize(IST) if now_ts.tzinfo is None else now_ts.tz_convert(IST)

    if manual_date is not None:
        d = pd.Timestamp(manual_date).normalize()
        info = calendar.session_info(d)
        if not info.is_trading_day:
            raise AnalysisDateError(
                f"{manual_date} is not an NSE cash-equity trading session "
                f"(weekend or exchange holiday). Refusing to silently roll to another "
                f"date — pass an actual trading date."
            )
        return AnalysisDateResolution(
            requested_date=manual_date,
            resolved_signal_date=d,
            is_trading_day=True,
            is_session_complete=True,  # manual historical scans are always treated as complete
            session_open=info.session_open,
            session_close=info.session_close,
            calendar_source=calendar.calendar_source,
            calendar_version=calendar.calendar_version,
            mode="MANUAL",
            reason="manual historical scan of an explicitly requested, validated trading session",
        )

    # AUTOMATIC mode: search backward (bounded) for the latest session whose close <= now.
    cursor = now_ts.normalize()
    for _ in range(30):
        info = calendar.session_info(cursor)
        if info.is_trading_day and info.session_close is not None and now_ts >= info.session_close:
            return AnalysisDateResolution(
                requested_date=None,
                resolved_signal_date=cursor.tz_localize(None),
                is_trading_day=True,
                is_session_complete=True,
                session_open=info.session_open,
                session_close=info.session_close,
                calendar_source=calendar.calendar_source,
                calendar_version=calendar.calendar_version,
                mode="AUTOMATIC",
                reason=(
                    "latest completed NSE cash-equity session as of "
                    f"{now_ts.isoformat()} IST"
                ),
            )
        cursor = cursor - pd.Timedelta(days=1)
    raise AnalysisDateError(
        f"Could not resolve a completed NSE session within 30 days back from {now_ts}. "
        f"This almost certainly indicates a calendar-provider problem, not an actual "
        f"30-day market closure — investigate before proceeding."
    )
