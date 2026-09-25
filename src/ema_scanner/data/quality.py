"""Data quality gates (notebook Cell 12; audit row 15; Phase-2 Sections 24-25 -- BLOCKER).

Marks rows/issues rather than silently deleting them (brief Section 19).
Staleness is computed in TRADING SESSIONS via the exchange calendar, not
calendar days (brief Section 20 -- audit Section 4: this was a real bug in
the notebook, where the configured threshold was never actually enforced).

**Bugs fixed (Phase-2 Sections 24-25):**
1. Duplicate dates and a non-monotonic index were previously only WARN-level
   issues (added to the issue list but not counted toward `hard_fail`) --
   i.e. data with duplicate/out-of-order timestamps could still be marked
   PASS/WARN and used for signals. They are now hard FAIL conditions.
2. `eligible_for_signal` is now a first-class field: True only when status is
   not FAIL AND (if `as_of_date`/the resolved analysis date was supplied) that
   exact date's bar is actually present in the series -- i.e. the
   analysis-date data gate (brief Phase-2 Section 6) is enforced HERE, not
   left to callers to remember to check. A missing analysis-date bar is
   reported as its own explicit issue (`DATA_MISSING_ANALYSIS_SESSION`) and
   is a hard FAIL for `eligible_for_signal`, even if the rest of the series
   looks fine -- the system must never silently fall back to "the previous
   available bar" instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar

QUALITY_PASS, QUALITY_WARN, QUALITY_FAIL = "PASS", "WARN", "FAIL"


@dataclass
class QualityReport:
    status: str
    issues: list[str] = field(default_factory=list)
    sessions_since_last_valid_bar: int | None = None
    missing_expected_sessions: int = 0
    eligible_for_signal: bool = False
    analysis_date_bar_present: bool | None = None  # None means "not checked" (no as_of_date given)


def validate_ohlc(
    df: pd.DataFrame, calendar: NSECalendar, as_of_date: pd.Timestamp | None = None, max_stale_sessions: int = 5,
) -> QualityReport:
    issues: list[str] = []
    if df.empty:
        return QualityReport(status=QUALITY_FAIL, issues=["empty dataframe"], eligible_for_signal=False)

    required = {"Open", "High", "Low", "Close", "Volume"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        return QualityReport(status=QUALITY_FAIL, issues=[f"missing columns: {sorted(missing_cols)}"], eligible_for_signal=False)

    dup = int(df.index.duplicated().sum())
    if dup:
        issues.append(f"HARD_FAIL: {dup} duplicate date(s) -- never signal-eligible")
    monotonic_ok = df.index.is_monotonic_increasing
    if not monotonic_ok:
        issues.append("HARD_FAIL: index not strictly increasing -- never signal-eligible")

    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    non_numeric = [c for c in numeric_cols if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        issues.append(f"non-numeric columns: {non_numeric}")

    non_positive = bool((df[["Open", "High", "Low", "Close"]] <= 0).any(axis=None))
    if non_positive:
        issues.append("non-positive price(s) found")

    bad_hl = int((df["High"] < df["Low"]).sum())
    if bad_hl:
        issues.append(f"{bad_hl} row(s) with High < Low")
    bad_ho = int((df["High"] < df["Open"]).sum())
    bad_hc = int((df["High"] < df["Close"]).sum())
    bad_lo = int((df["Low"] > df["Open"]).sum())
    bad_lc = int((df["Low"] > df["Close"]).sum())
    for label, cnt in [("High<Open", bad_ho), ("High<Close", bad_hc), ("Low>Open", bad_lo), ("Low>Close", bad_lc)]:
        if cnt:
            issues.append(f"{cnt} row(s) with {label}")

    # abnormal single-day gap flag (WARN, not FAIL -- corporate actions can cause real large gaps)
    daily_ret = df["Close"].pct_change().abs()
    abnormal_gaps = int((daily_ret > 0.30).sum())
    if abnormal_gaps:
        issues.append(f"{abnormal_gaps} day(s) with >30% single-day move (verify vs. corporate actions)")

    sessions_since_last, missing_expected = None, 0
    analysis_date_bar_present = None
    if as_of_date is not None:
        last_date = df.index.max()
        sessions_since_last = calendar.sessions_between(last_date, as_of_date)
        if sessions_since_last > max_stale_sessions:
            issues.append(
                f"stale: {sessions_since_last} completed trading session(s) since last bar "
                f"({last_date.date()}), threshold is {max_stale_sessions}"
            )
        expected_sessions = calendar.valid_sessions(df.index.min(), df.index.max())
        missing_expected = len(set(expected_sessions) - set(df.index))
        if missing_expected:
            issues.append(f"{missing_expected} expected trading session(s) missing from the series")

        # Phase-2 Section 6/25: the resolved analysis date must exist as an
        # ACTUAL bar -- never silently substitute the previous available bar.
        analysis_date_bar_present = as_of_date in df.index
        if not analysis_date_bar_present:
            issues.append(f"DATA_MISSING_ANALYSIS_SESSION: no bar present for resolved analysis date {as_of_date.date()}")

    hard_fail = bool(non_positive) or bad_hl > 0 or non_numeric or missing_cols or dup > 0 or not monotonic_ok
    status = QUALITY_FAIL if hard_fail else (QUALITY_WARN if issues else QUALITY_PASS)

    eligible_for_signal = (status != QUALITY_FAIL) and (analysis_date_bar_present is not False)
    return QualityReport(
        status=status, issues=issues, sessions_since_last_valid_bar=sessions_since_last,
        missing_expected_sessions=missing_expected, eligible_for_signal=eligible_for_signal,
        analysis_date_bar_present=analysis_date_bar_present,
    )
