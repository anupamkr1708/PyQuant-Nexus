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


def build_true_weekly_ohlc(daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregates daily bars into weekly OHLCV, grouped by the trading-calendar
    week actually present in the data (see module docstring point 1). The weekly
    row is indexed by `WeekEnd` = the LAST trading session date in that week
    (equivalent to the notebook's W-FRI label in an ordinary week)."""
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
    week_end_dates = grouped.apply(lambda g: g.index.max())
    weekly.index = pd.DatetimeIndex(week_end_dates.values, name="WeekEnd")
    weekly = weekly.sort_index()
    weekly = weekly.dropna(subset=["Open", "High", "Low", "Close"])
    return weekly


def attach_last_known_weekly(
    daily_with_emas: pd.DataFrame, weekly_with_emas: pd.DataFrame, weekly_cols: list[str]
) -> pd.DataFrame:
    """As-of merges each daily row with the latest weekly row whose `WeekEnd` is
    `<= ` that daily date (non-strict — see module docstring point 2). Never uses
    a weekly row whose WeekEnd is AFTER the daily date (that would be look-ahead)."""
    d = daily_with_emas.sort_index().copy()
    w = weekly_with_emas.sort_index().copy()[weekly_cols]
    left = d.reset_index().rename(columns={d.index.name or "index": "Date"}).sort_values("Date")
    right = w.reset_index().rename(columns={"WeekEnd": "WeekEnd"}).sort_values("WeekEnd")
    merged = pd.merge_asof(
        left, right, left_on="Date", right_on="WeekEnd", direction="backward",
        allow_exact_matches=True,  # <-- the fix: WeekEnd == Date is ELIGIBLE (non-strict <=)
    )
    merged = merged.set_index("Date")
    merged["Weekly_Period_End"] = merged["WeekEnd"]
    merged = merged.drop(columns=["WeekEnd"])
    return merged


def latest_known_weekly_row(weekly_with_emas: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.Series | None:
    """Scalar version of the availability rule above, used by regression tests."""
    eligible = weekly_with_emas[weekly_with_emas.index <= as_of_date]
    return None if eligible.empty else eligible.iloc[-1]
