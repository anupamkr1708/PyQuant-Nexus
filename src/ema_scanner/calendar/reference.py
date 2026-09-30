"""Calendar reference data model (Phase-3 BLOCKER 8).

A special-session record distinguishes two DIFFERENT facts that must never be
conflated:

    known trading DATE      -- the exchange has said a session will occur on
                                this date (e.g. Muhurat Trading, Sun 8 Nov 2026).
    known exact session TIMING -- the exchange has separately notified the
                                open/close times.

An entry can legitimately have `is_trading_day=True` with
`session_open=None, session_close=None, timing_verified=False`: "a session
happens that day, exact times not yet known to this system". Validation
REFUSES an entry that supplies times without `timing_verified=True` -- an
unverified time is never accepted into the calendar (brief: "Do not infer an
unverified time").

Every entry carries provenance (`source`, `source_url`, `verified_at`,
`official_document_verified`) so the calendar's special-session data has an
explicit authoritative data path rather than being silently trusted.
`calendar_version` is recorded so a run manifest can identify exactly which
reference data was in force.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

SessionType = Literal["REGULAR", "MUHURAT", "SPECIAL", "HOLIDAY"]

DEFAULT_REFERENCE_PATH = Path(__file__).resolve().parents[3] / "configs" / "nse_special_sessions.yaml"


class CalendarReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class CalendarReferenceEntry:
    date: str  # ISO YYYY-MM-DD
    is_trading_day: bool
    session_type: SessionType
    session_open: str | None  # "HH:MM" IST, or None if timing not verified
    session_close: str | None
    timing_verified: bool
    source: str
    source_url: str | None
    verified_at: str | None
    official_document_verified: bool
    calendar_version: str
    note: str | None = None

    def validate(self) -> None:
        if not self.timing_verified and (self.session_open is not None or self.session_close is not None):
            raise CalendarReferenceError(
                f"{self.date}: session_open/close supplied but timing_verified=False -- an unverified "
                f"time must never enter the calendar. Leave both None until the exchange's own "
                f"notification has been checked."
            )
        if self.timing_verified and (self.session_open is None or self.session_close is None):
            raise CalendarReferenceError(f"{self.date}: timing_verified=True requires both session_open and session_close.")
        if not self.is_trading_day and self.session_type not in ("HOLIDAY",):
            raise CalendarReferenceError(f"{self.date}: is_trading_day=False must use session_type=HOLIDAY.")


def load_reference_entries(path: str | Path | None = None) -> list[CalendarReferenceEntry]:
    p = Path(path) if path else DEFAULT_REFERENCE_PATH
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or {}
    version = raw.get("calendar_version", "unversioned")
    entries = []
    for item in raw.get("entries", []):
        entry = CalendarReferenceEntry(
            date=str(item["date"]), is_trading_day=bool(item["is_trading_day"]),
            session_type=item["session_type"], session_open=item.get("session_open"),
            session_close=item.get("session_close"), timing_verified=bool(item.get("timing_verified", False)),
            source=item["source"], source_url=item.get("source_url"), verified_at=item.get("verified_at"),
            official_document_verified=bool(item.get("official_document_verified", False)),
            calendar_version=version, note=item.get("note"),
        )
        entry.validate()
        entries.append(entry)
    return entries
