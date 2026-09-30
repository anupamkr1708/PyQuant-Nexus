"""Weekly context engine (notebook Cell 16; docs/NOTEBOOK_AUDIT.md §3 and row 17).

Two changes versus the notebook, both documented in NOTEBOOK_AUDIT.md §3 and
covered by tests/lookahead/test_weekly_availability.py:

1. Weekly grouping is by the ACTUAL ISO (year, week) of trading sessions present
   in the data, not a fixed `resample("W-FRI")` anchor. In an ordinary Mon-Fri
   week with no holidays these are equivalent; they diverge only around holidays
   and irregular sessions (e.g. a Saturday special session), which a fixed-anchor
   resample can misclassify (brief Section 9).

2. A weekly candle is eligible for use on daily date D once its own week has
   fully closed, i.e. `weekly_period_end <= D` (non-strict). The notebook used a
   strict `<` (via a `-1 nanosecond` as-of key), which made a week's own
   just-closed Friday candle unusable until the following Monday — the brief
   calls this "more conservative than necessary" (Section 9) and gives the
   Friday example explicitly. This system is EOD-only (Section 12): the decision
   timestamp for daily date D is understood to be D's own session close, and a
   weekly period's data becomes available at ITS OWN last session's close — so
   `weekly_period_end <= D` is exactly the correct availability boundary, not an
   approximation.

SOURCE-DERIVED RULE preserved unchanged: weekly = structural confirmation
context, daily = setup/entry context; a daily signal may only use a weekly
candle whose period has actually closed.
"""
from __future__ import annotations

import pandas as pd

REQUIRED_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def trading_week_id(index: pd.DatetimeIndex) -> pd.Series:
    """(ISO year, ISO week) label per date, derived purely from the dates actually
    present — no external calendar dependency, so this stays a pure, independently
    testable function (brief Section 26)."""
    iso = pd.Index(index).isocalendar()
    return pd.Series([f"{y:04d}-W{w:02d}" for y, w in zip(iso["year"], iso["week"])], index=index)


def build_true_weekly_ohlc(daily: pd.DataFrame, expected_week_ends: pd.Series | None = None) -> pd.DataFrame:
    """Aggregates daily bars into weekly OHLCV, grouped by the trading-calendar
    week actually present in the data (see module docstring point 1). The weekly
    row is indexed by `WeekEnd` = the LAST OBSERVED trading session date in that
    week (equivalent to the notebook's W-FRI label in an ordinary week).

    **Phase-3 BLOCKER 8:** `expected_week_ends` (from
    `NSECalendar.expected_week_ends`, indexed by ISO week label) supplies the
    exchange-scheduled LAST SESSION of each week. It is exposed as an
    `ExpectedWeekEnd` column and is what `attach_last_known_weekly` uses as the
    availability boundary. This matters when the calendar schedules a session
    AFTER the last bar present -- e.g. a Sunday Muhurat session following a
    Friday: on Friday's EOD the week is NOT complete (a scheduled session
    remains), so Friday's partial weekly candle must not be treated as final
    merely because no Sunday row exists yet. Without a calendar the boundary
    falls back to the observed last bar (documented, weaker behavior).
    `ExpectedWeekEnd` is never earlier than the observed last bar."""
    daily = daily.sort_index()
    week_id = trading_week_id(daily.index)
    grouped = daily.groupby(week_id)
    weekly = grouped.agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    )
    observed_ends = grouped.apply(lambda g: g.index.max())
    weekly.index = pd.DatetimeIndex(observed_ends.values, name="WeekEnd")
    if expected_week_ends is not None:
        labels = list(observed_ends.index)
        scheduled = [expected_week_ends.get(lbl, pd.NaT) for lbl in labels]
        expected = [max(o, sc) if pd.notna(sc) else o for o, sc in zip(observed_ends.values, scheduled)]
        weekly["ExpectedWeekEnd"] = pd.DatetimeIndex(expected)
    weekly = weekly.sort_index()
    weekly = weekly.dropna(subset=["Open", "High", "Low", "Close"])
    return weekly


def attach_last_known_weekly(
    daily_with_emas: pd.DataFrame, weekly_with_emas: pd.DataFrame, weekly_cols: list[str]
) -> pd.DataFrame:
    """As-of merges each daily row with the latest weekly row whose AVAILABILITY
    DATE is `<=` that daily date (non-strict -- see module docstring point 2).
    The availability date is `ExpectedWeekEnd` when the weekly frame carries it
    (calendar-aware, Phase-3 BLOCKER 8), else the observed `WeekEnd`. Never uses
    a weekly row whose availability date is AFTER the daily date (look-ahead)."""
    d = daily_with_emas.sort_index().copy()
    w = weekly_with_emas.sort_index().reset_index()  # exposes the "WeekEnd" index as a column
    availability_source = "ExpectedWeekEnd" if "ExpectedWeekEnd" in w.columns else "WeekEnd"
    right = w[["WeekEnd", *weekly_cols]].rename(columns={"WeekEnd": "Weekly_Period_End"})
    right["_availability_date"] = w[availability_source].to_numpy()
    right = right.sort_values("_availability_date")
    left = d.reset_index().rename(columns={d.index.name or "index": "Date"}).sort_values("Date")
    merged = pd.merge_asof(
        left, right, left_on="Date", right_on="_availability_date", direction="backward",
        allow_exact_matches=True,  # availability date == Date is ELIGIBLE (non-strict <=)
    )
    merged = merged.set_index("Date")
    merged = merged.rename(columns={"_availability_date": "Weekly_Availability_Date"})
    return merged


def latest_known_weekly_row(weekly_with_emas: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.Series | None:
    """Scalar version of the availability rule above, used by regression tests."""
    if "ExpectedWeekEnd" in weekly_with_emas.columns:
        eligible = weekly_with_emas[weekly_with_emas["ExpectedWeekEnd"] <= as_of_date]
    else:
        eligible = weekly_with_emas[weekly_with_emas.index <= as_of_date]
    return None if eligible.empty else eligible.iloc[-1]
