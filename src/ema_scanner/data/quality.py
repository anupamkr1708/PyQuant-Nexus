"""Data quality gates (notebook Cell 12; audit row 15; Phase-2 Sections 24-25;
Phase-3 BLOCKERS 9, 10).

Marks rows/issues rather than silently deleting them (brief Section 19).
Staleness is computed in TRADING SESSIONS via the exchange calendar, not
calendar days (brief Section 20).

**Bugs fixed (Phase-2 Sections 24-25):** duplicate dates / non-monotonic
index are hard FAIL; `eligible_for_signal` enforces the analysis-date data
gate (brief Phase-2 Section 6) directly.

**Bug fixed (Phase-3 BLOCKER 9):** NaN / +inf / -inf in Open/High/Low/Close/
Volume are now explicitly detected and are a hard FAIL -- never signal-
eligible. v1's numeric-dtype check alone did NOT catch this (a float64
column full of NaN/inf is still "numeric" by `pd.api.types.is_numeric_dtype`).

**Bug fixed (Phase-3 BLOCKER 10):** the index CONTRACT is now checked
explicitly rather than trusted from the provider: must be a `DatetimeIndex`
(not merely "sortable"), must be tz-naive (this codebase's convention
throughout -- calendar/features assume naive, midnight-normalized dates), and
must be normalized to midnight (no leftover intraday time component that
could silently break `.loc[date]` lookups elsewhere in the pipeline). A
provider is never trusted merely because it currently happens to behave --
these are checked, not assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ema_scanner.calendar.nse import NSECalendar

QUALITY_PASS, QUALITY_WARN, QUALITY_FAIL = "PASS", "WARN", "FAIL"
OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]


@dataclass
class QualityReport:
    status: str
    issues: list[str] = field(default_factory=list)
    sessions_since_last_valid_bar: int | None = None
    missing_expected_sessions: int = 0
    eligible_for_signal: bool = False
    analysis_date_bar_present: bool | None = None  # None means "not checked" (no as_of_date given)


def _check_index_contract(df: pd.DataFrame) -> list[str]:
    """Phase-3 BLOCKER 10: never assume, always check."""
    issues = []
    if not isinstance(df.index, pd.DatetimeIndex):
        issues.append(f"HARD_FAIL: index is not a DatetimeIndex (got {type(df.index).__name__})")
        return issues  # further checks below assume DatetimeIndex; bail out early
    if df.index.tz is not None:
        issues.append(f"HARD_FAIL: index is timezone-aware ({df.index.tz}) -- this codebase's convention is tz-naive throughout")
    non_normalized = int((df.index != df.index.normalize()).sum())
    if non_normalized:
        issues.append(f"HARD_FAIL: {non_normalized} index timestamp(s) have a non-midnight time component (not normalized to daily sessions)")
    return issues


def validate_ohlc(
    df: pd.DataFrame, calendar: NSECalendar, as_of_date: pd.Timestamp | None = None, max_stale_sessions: int = 5,
) -> QualityReport:
    issues: list[str] = []
    if df.empty:
        return QualityReport(status=QUALITY_FAIL, issues=["empty dataframe"], eligible_for_signal=False)

    required = set(OHLCV_COLS)
    missing_cols = required - set(df.columns)
    if missing_cols:
        return QualityReport(status=QUALITY_FAIL, issues=[f"missing columns: {sorted(missing_cols)}"], eligible_for_signal=False)

    index_issues = _check_index_contract(df)
    issues.extend(index_issues)
    index_hard_fail = bool(index_issues)

    dup = int(df.index.duplicated().sum())
    if dup:
        issues.append(f"HARD_FAIL: {dup} duplicate date(s) -- never signal-eligible")
    monotonic_ok = df.index.is_monotonic_increasing
    if not monotonic_ok:
        issues.append("HARD_FAIL: index not strictly increasing -- never signal-eligible")

    numeric_cols = OHLCV_COLS
    non_numeric = [c for c in numeric_cols if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        issues.append(f"non-numeric columns: {non_numeric}")

    # Phase-3 BLOCKER 9: NaN / +inf / -inf explicitly detected -- a numeric
    # dtype check alone does NOT catch these.
    non_finite_counts = {}
    if not non_numeric:
        for col in numeric_cols:
            vals = df[col].to_numpy(dtype=float)
            n_nan = int(np.isnan(vals).sum())
            n_inf = int(np.isinf(vals).sum())
            if n_nan or n_inf:
                non_finite_counts[col] = {"nan": n_nan, "inf": n_inf}
    if non_finite_counts:
        detail = ", ".join(f"{c}: {v['nan']} NaN / {v['inf']} inf" for c, v in non_finite_counts.items())
        issues.append(f"HARD_FAIL: non-finite values found ({detail}) -- never signal-eligible")

    non_positive = False
    bad_hl = 0
    if not non_numeric and not non_finite_counts:
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

        daily_ret = df["Close"].pct_change().abs()
        abnormal_gaps = int((daily_ret > 0.30).sum())
        if abnormal_gaps:
            issues.append(f"{abnormal_gaps} day(s) with >30% single-day move (verify vs. corporate actions)")

    sessions_since_last, missing_expected = None, 0
    analysis_date_bar_present = None
    if as_of_date is not None and not index_hard_fail:
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

        analysis_date_bar_present = as_of_date in df.index
        if not analysis_date_bar_present:
            issues.append(f"DATA_MISSING_ANALYSIS_SESSION: no bar present for resolved analysis date {as_of_date.date()}")

    hard_fail = (
        bool(non_positive) or bad_hl > 0 or non_numeric or missing_cols or dup > 0 or not monotonic_ok
        or index_hard_fail or bool(non_finite_counts)
    )
    status = QUALITY_FAIL if hard_fail else (QUALITY_WARN if issues else QUALITY_PASS)

    eligible_for_signal = (status != QUALITY_FAIL) and (analysis_date_bar_present is not False)
    return QualityReport(
        status=status, issues=issues, sessions_since_last_valid_bar=sessions_since_last,
        missing_expected_sessions=missing_expected, eligible_for_signal=eligible_for_signal,
        analysis_date_bar_present=analysis_date_bar_present,
    )
