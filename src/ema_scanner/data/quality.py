"""Data quality gates (notebook Cell 12; audit row 15, and audit §4 bug rows).

Marks rows/issues rather than silently deleting them (brief Section 19).
Staleness is computed in TRADING SESSIONS via the exchange calendar, not
calendar days (brief Section 20 — audit §4: this was a real bug in the
notebook, where the configured threshold was never actually enforced).
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


def validate_ohlc(
    df: pd.DataFrame, calendar: NSECalendar, as_of_date: pd.Timestamp | None = None, max_stale_sessions: int = 5,
) -> QualityReport:
    issues: list[str] = []
    if df.empty:
        return QualityReport(status=QUALITY_FAIL, issues=["empty dataframe"])

    required = {"Open", "High", "Low", "Close", "Volume"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        return QualityReport(status=QUALITY_FAIL, issues=[f"missing columns: {sorted(missing_cols)}"])

    dup = df.index.duplicated().sum()
    if dup:
        issues.append(f"{dup} duplicate date(s)")
    if not df.index.is_monotonic_increasing:
        issues.append("index not strictly increasing")

    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    non_numeric = [c for c in numeric_cols if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        issues.append(f"non-numeric columns: {non_numeric}")

    non_positive = (df[["Open", "High", "Low", "Close"]] <= 0).any(axis=None)
    if non_positive:
        issues.append("non-positive price(s) found")

    bad_hl = (df["High"] < df["Low"]).sum()
    if bad_hl:
        issues.append(f"{bad_hl} row(s) with High < Low")
    bad_ho = (df["High"] < df["Open"]).sum()
    bad_hc = (df["High"] < df["Close"]).sum()
    bad_lo = (df["Low"] > df["Open"]).sum()
    bad_lc = (df["Low"] > df["Close"]).sum()
    for label, cnt in [("High<Open", bad_ho), ("High<Close", bad_hc), ("Low>Open", bad_lo), ("Low>Close", bad_lc)]:
        if cnt:
            issues.append(f"{cnt} row(s) with {label}")

    # abnormal single-day gap flag (WARN, not FAIL — corporate actions can cause real large gaps)
    daily_ret = df["Close"].pct_change().abs()
    abnormal_gaps = int((daily_ret > 0.30).sum())
    if abnormal_gaps:
        issues.append(f"{abnormal_gaps} day(s) with >30% single-day move (verify vs. corporate actions)")

    sessions_since_last, missing_expected = None, 0
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

    hard_fail = bool(non_positive) or bad_hl > 0 or non_numeric or missing_cols
    status = QUALITY_FAIL if hard_fail else (QUALITY_WARN if issues else QUALITY_PASS)
    return QualityReport(
        status=status, issues=issues, sessions_since_last_valid_bar=sessions_since_last,
        missing_expected_sessions=missing_expected,
    )
