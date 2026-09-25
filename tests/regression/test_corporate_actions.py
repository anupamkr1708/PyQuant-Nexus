"""Corporate-action regression tests (Phase-2 Section 1 BLOCKER, Section 26).

Proves RAW, SPLIT_ADJUSTED, and TOTAL_RETURN remain DISTINCT, and specifically
proves the fixed bug: SPLIT_ADJUSTED must NOT move on a dividend-only day, and
must NOT equal AdjClose/Close-derived values when a dividend is present.
"""
import numpy as np
import pandas as pd

from ema_scanner.data.corporate_actions import compute_split_adjustment_factors
from ema_scanner.data.normalization import normalize_provider_frame, total_return_close


def _fixture_with_split_and_dividend() -> pd.DataFrame:
    """10 days flat at 100 RAW Close. A 2-for-1 SPLIT on day 5 (so days 0-4
    were "really" worth 200 pre-split-equivalent, i.e. RAW shows a
    discontinuity: 100 before, 100 after -- wait, we construct RAW so the
    provider's own convention holds: raw Close reports the CURRENT-day actual
    traded price, so a forward split just changes the per-share price level
    for days AFTER the split relative to days BEFORE. We build RAW as if the
    split just happened: days 0-4 trade around 200 (pre-split), days 5-9
    trade around 100 (post-split, half the price, double the volume) -- a 2:1
    split ratio recorded on day 5. A DIVIDEND (no split) is recorded on day 8
    with no corresponding price discontinuity in RAW (as is standard: cash
    dividends don't force a raw price discontinuity in daily bar data the way
    yfinance reports it -- AdjClose is what incorporates the dividend
    retroactively)."""
    n = 10
    dates = pd.bdate_range("2024-01-01", periods=n)
    raw_close = np.array([200.0] * 5 + [100.0] * 5)
    df = pd.DataFrame({
        "Open": raw_close, "High": raw_close + 1, "Low": raw_close - 1, "Close": raw_close,
        "Volume": [1000.0] * 5 + [2000.0] * 5,
        "Stock Splits": [0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0],
        "Dividends": [0.0] * 8 + [5.0] + [0.0],
    }, index=dates)
    # AdjClose incorporates BOTH the split AND the dividend: for days before the
    # split, AdjClose = raw_close / 2 (split) further reduced for the dividend
    # that happens later (a dividend on day 8 retroactively lowers AdjClose for
    # all earlier days by roughly dividend/price). We construct a plausible
    # AdjClose reflecting that compounded effect distinctly from a pure split factor.
    split_factor = compute_split_adjustment_factors(df["Stock Splits"])
    pure_split_adjusted = raw_close * split_factor.to_numpy()
    # Now further reduce pre-dividend-date rows by the dividend's proportional effect,
    # to simulate what Yahoo's AdjClose actually does (total return, not pure split).
    div_factor = np.where(np.arange(n) < 8, 1 - 5.0 / 100.0, 1.0)
    df["AdjClose"] = pure_split_adjusted * div_factor
    return df


def test_raw_ohlcv_is_untouched():
    df = _fixture_with_split_and_dividend()
    out = normalize_provider_frame(df, "RAW")
    assert (out["Close"] == df["Close"]).all()


def test_split_adjusted_removes_the_split_discontinuity_only():
    df = _fixture_with_split_and_dividend()
    out = normalize_provider_frame(df, "SPLIT_ADJUSTED")
    # After pure split adjustment, ALL 10 days should show the SAME price level
    # (100), because the only real discontinuity was the 2:1 split -- the
    # dividend must NOT have moved this series at all.
    assert np.allclose(out["Close"].to_numpy(), 100.0, atol=1e-9)


def test_split_adjusted_is_not_derived_from_adjclose_over_close():
    """This is the exact bug fixed: SPLIT_ADJUSTED must differ from
    AdjClose/Close * Close (i.e. from AdjClose itself) whenever a dividend is
    present, because AdjClose bakes in the dividend and SPLIT_ADJUSTED must not."""
    df = _fixture_with_split_and_dividend()
    split_adjusted = normalize_provider_frame(df, "SPLIT_ADJUSTED")["Close"]
    naive_wrong_way = df["AdjClose"]  # what v1 used to (mis)produce as "split adjusted"
    # They must differ on the pre-dividend days precisely because of the
    # dividend contamination in AdjClose.
    assert not np.allclose(split_adjusted.iloc[:8].to_numpy(), naive_wrong_way.iloc[:8].to_numpy())


def test_total_return_close_is_exposed_separately_and_differs_from_split_adjusted():
    df = _fixture_with_split_and_dividend()
    split_adjusted = normalize_provider_frame(df, "SPLIT_ADJUSTED")["Close"]
    tr = total_return_close(df)
    assert tr is not None
    assert not np.allclose(split_adjusted.iloc[:8].to_numpy(), tr.iloc[:8].to_numpy())


def test_split_adjustment_volume_scales_inversely_to_price():
    df = _fixture_with_split_and_dividend()
    out = normalize_provider_frame(df, "SPLIT_ADJUSTED")
    # Pre-split days' volume should be scaled UP (more "new-share-equivalent" volume)
    assert out["Volume"].iloc[0] > df["Volume"].iloc[0]
    # Post-split days' volume is unaffected (factor == 1 after the split)
    assert out["Volume"].iloc[-1] == df["Volume"].iloc[-1]


def test_total_return_adjusted_ohlcv_mode_raises_rather_than_fakes_it():
    import pytest
    df = _fixture_with_split_and_dividend()
    with pytest.raises(NotImplementedError):
        normalize_provider_frame(df, "TOTAL_RETURN_ADJUSTED")


def test_no_split_column_falls_back_to_raw_not_to_adjclose():
    dates = pd.bdate_range("2024-01-01", periods=5)
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000.0}, index=dates)
    out = normalize_provider_frame(df, "SPLIT_ADJUSTED")
    assert (out["Close"] == 100.0).all()
