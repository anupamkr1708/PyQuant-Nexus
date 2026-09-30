"""Weekly no-lookahead tests (brief Section 74 Test D; Section 75; Section 93 #12-13).

Pins BOTH the corrected behavior (Friday can use its own just-closed weekly
candle) AND the invariant that no future data ever leaks into a past date.
See docs/NOTEBOOK_AUDIT.md §3 for why the boundary moved from strict `<` to `<=`.
"""
import pandas as pd

from ema_scanner.features.ema import compute_all_emas
from ema_scanner.features.weekly import (
    attach_last_known_weekly,
    build_true_weekly_ohlc,
    latest_known_weekly_row,
)
from tests.fixtures.synthetic import make_synthetic_ohlcv


def _build(daily):
    d = compute_all_emas(daily)
    weekly = build_true_weekly_ohlc(daily)
    w = compute_all_emas(weekly, suffix="_W")
    return d, w


def test_friday_may_use_its_own_just_closed_weekly_candle():
    daily = make_synthetic_ohlcv(400, seed=40)
    _, w = _build(daily)
    fridays_that_are_weekends = [d for d in w.index if d.weekday() == 4]
    assert fridays_that_are_weekends, "fixture should contain at least one Friday week-end"
    friday = fridays_that_are_weekends[10]
    row = latest_known_weekly_row(w, friday)
    assert row.name == friday  # THE FIX: non-strict <=, Friday sees its own week


def test_thursday_cannot_use_that_same_weeks_candle():
    daily = make_synthetic_ohlcv(400, seed=41)
    _, w = _build(daily)
    fridays = [d for d in w.index if d.weekday() == 4]
    friday = fridays[10]
    thursday_candidates = daily.index[daily.index < friday]
    thursday = thursday_candidates[-1]
    if thursday.weekday() != 3:
        return  # holiday-shifted week; skip rather than assert something not guaranteed
    row = latest_known_weekly_row(w, thursday)
    assert row.name < friday


def test_appending_future_rows_does_not_change_prior_merged_weekly_values():
    """Brief Section 74 Test A/B/D combined."""
    daily_full = make_synthetic_ohlcv(600, seed=42)
    cutoff = daily_full.index[400]
    daily_partial = daily_full.loc[:cutoff]

    d_full, w_full = _build(daily_full)
    merged_full = attach_last_known_weekly(d_full, w_full, ["EMA10_W", "EMA20_W", "EMA89_W", "EMA200_W"])

    d_partial, w_partial = _build(daily_partial)
    merged_partial = attach_last_known_weekly(d_partial, w_partial, ["EMA10_W", "EMA20_W", "EMA89_W", "EMA200_W"])

    check_date = daily_full.index[300]
    cols = ["EMA10_W", "EMA20_W", "EMA89_W", "EMA200_W"]
    a = merged_full.loc[check_date, cols].astype(float)
    b = merged_partial.loc[check_date, cols].astype(float)
    assert (a - b).abs().max() < 1e-9, "appending one month+ of future data changed an older weekly-derived value"


def test_appending_one_month_of_future_data_does_not_alter_older_signals():
    """Brief Section 74 Test B, at the full feature-frame level."""
    from ema_scanner.config import load_config
    from ema_scanner.features.regime import compute_market_regime
    from ema_scanner.strategy.signal_engine import build_stock_feature_frame

    daily_full = make_synthetic_ohlcv(700, seed=43)
    cutoff = daily_full.index[600]  # leaves ~1 month+ of "future" data beyond cutoff
    daily_partial = daily_full.loc[:cutoff]
    index_full = make_synthetic_ohlcv(700, seed=44)[["Close"]]

    cfg = load_config()
    regime_full = compute_market_regime(index_full)
    regime_partial = compute_market_regime(index_full.loc[:cutoff])

    feats_full = build_stock_feature_frame(daily_full, index_full["Close"], regime_full, cfg)
    feats_partial = build_stock_feature_frame(daily_partial, index_full["Close"].loc[:cutoff], regime_partial, cfg)

    check_date = daily_full.index[500]
    compare_cols = ["Daily_State", "Weekly_State", "Cluster_Width_Pct", "Pullback_State", "Signal_State"]
    for col in compare_cols:
        v_full, v_partial = feats_full.loc[check_date, col], feats_partial.loc[check_date, col]
        if pd.isna(v_full) and pd.isna(v_partial):
            continue
        assert v_full == v_partial, f"column {col} at {check_date} changed after appending future data: {v_full!r} vs {v_partial!r}"


def test_holiday_shortened_week_uses_the_actual_last_present_session_as_weekend():
    """Phase-2 Section 8: a week missing one weekday (simulating a holiday)
    must use the LAST ACTUALLY-PRESENT session of that week as WeekEnd, not
    assume Friday is always present."""
    dates = pd.bdate_range("2024-01-01", periods=60)  # all business days
    # Remove one Friday to simulate a holiday-shortened week.
    fridays = [d for d in dates if d.weekday() == 4]
    holiday_friday = fridays[3]
    daily = make_synthetic_ohlcv(60, seed=45, start="2024-01-01")
    daily = daily.drop(index=holiday_friday)

    weekly = build_true_weekly_ohlc(daily)
    week_containing_holiday = [w for w in weekly.index if abs((w - holiday_friday).days) <= 4]
    assert week_containing_holiday, "expected a weekly row near the holiday week"
    week_end = week_containing_holiday[0]
    # WeekEnd must be the Thursday (last real session that week), not the
    # (missing) Friday, and must not be some later week's Friday either.
    assert week_end.weekday() == 3  # Thursday
    assert week_end != holiday_friday


def test_thursday_never_sees_an_incomplete_current_week_even_with_holiday_shortening():
    dates = pd.bdate_range("2024-01-01", periods=60)
    fridays = [d for d in dates if d.weekday() == 4]
    holiday_friday = fridays[5]
    daily = make_synthetic_ohlcv(60, seed=46, start="2024-01-01").drop(index=holiday_friday)
    _, w = _build(daily)

    # The Wednesday of that same holiday-shortened week must NOT see that
    # week's own (still-forming) candle.
    wednesday_candidates = [d for d in daily.index if d.weekday() == 2 and d < holiday_friday and (holiday_friday - d).days <= 2]
    if not wednesday_candidates:
        return
    wednesday = wednesday_candidates[-1]
    row = latest_known_weekly_row(w, wednesday)
    thursday_of_that_week = holiday_friday - pd.Timedelta(days=1)
    assert row.name < thursday_of_that_week


def test_scheduled_sunday_session_after_friday_keeps_that_weeks_candle_open():
    """Phase-3 BLOCKER 8: if the exchange calendar schedules a session AFTER
    the last observed bar in a week (e.g. a Sunday Muhurat session following
    a Friday), Friday's EOD must NOT treat that week's candle as final merely
    because no Sunday row exists yet in the data -- the calendar's expected
    week boundary governs, not the observed last bar."""
    from ema_scanner.calendar.nse import NSECalendar

    cal = NSECalendar()
    # A short daily series ending on the Friday immediately before the
    # scheduled 2026-11-08 Sunday Muhurat session.
    dates = pd.bdate_range("2026-10-01", "2026-11-06")  # ends Friday 2026-11-06
    daily = make_synthetic_ohlcv(len(dates), seed=90, start="2026-10-01")
    daily = daily.iloc[: len(dates)]
    daily.index = dates[: len(daily)]

    expected_week_ends = cal.expected_week_ends(daily.index.min(), daily.index.max())
    weekly = build_true_weekly_ohlc(daily, expected_week_ends=expected_week_ends)

    last_friday = dates[-1]
    week_row = weekly.loc[weekly.index == last_friday]
    assert not week_row.empty
    # The calendar knows a session is scheduled for Sunday 2026-11-08, so the
    # EXPECTED close of that week must be AFTER the observed Friday bar.
    assert week_row["ExpectedWeekEnd"].iloc[0] > last_friday
    assert week_row["ExpectedWeekEnd"].iloc[0] == pd.Timestamp("2026-11-08")

    w = compute_all_emas(weekly, suffix="_W")
    # On the Friday itself, this week's candle must NOT be treated as
    # available yet (a scheduled session remains) -- the LAST available
    # weekly row must be from an EARLIER, already-fully-closed week.
    row_on_friday = latest_known_weekly_row(w, last_friday)
    assert row_on_friday.name < last_friday, (
        "Friday's own week must not be usable while a scheduled Sunday session "
        "for that same week has not yet occurred"
    )
