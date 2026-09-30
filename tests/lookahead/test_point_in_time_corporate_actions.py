"""BLOCKER 1 (Phase-3): point-in-time corporate-action handling.

Proves signal_features(D) is invariant to a corporate-action record whose
event date is AFTER D -- i.e. a future split must never alter a historical
signal calculated before the split occurred.
"""
import numpy as np
import pandas as pd

from ema_scanner.data.normalization import normalize_provider_frame


def _fixture_with_a_split(split_date_idx: int, n: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    # Raw price shows the provider's own convention: post-split day onward
    # trades at half the pre-split level (a clean 2:1 split).
    raw_close = np.where(np.arange(n) < split_date_idx, 200.0, 100.0).astype(float)
    stock_splits = np.zeros(n)
    stock_splits[split_date_idx] = 2.0
    return pd.DataFrame({
        "Open": raw_close, "High": raw_close + 1, "Low": raw_close - 1, "Close": raw_close,
        "Volume": 1000.0, "Stock Splits": stock_splits, "Dividends": 0.0,
    }, index=dates)


def test_point_in_time_split_adjustment_ignores_a_future_split():
    """The core invariant: adjusting AS OF a date BEFORE the split must be
    identical whether or not the future split row is even present in the
    dataframe passed in."""
    df_with_future_split = _fixture_with_a_split(split_date_idx=20, n=30)
    as_of = df_with_future_split.index[10]  # 10 days before the split

    adjusted_with_future_split_visible = normalize_provider_frame(
        df_with_future_split, "SPLIT_ADJUSTED", as_of_date=as_of
    )

    # Now simulate NOT having the future split at all (as if `as_of` were
    # the actual "today" and the split genuinely hadn't happened yet).
    df_truncated = df_with_future_split.loc[:as_of].copy()
    df_truncated["Stock Splits"] = 0.0  # no split has occurred as of this date
    adjusted_without_future_split = normalize_provider_frame(df_truncated, "SPLIT_ADJUSTED", as_of_date=as_of)

    a = adjusted_with_future_split_visible.loc[:as_of, "Close"].to_numpy()
    b = adjusted_without_future_split["Close"].to_numpy()
    assert np.allclose(a, b), (
        "SPLIT_ADJUSTED prices at/before `as_of_date` changed depending on whether "
        "a split dated AFTER as_of_date happened to be present in the raw data -- "
        "this is exactly the point-in-time leakage BLOCKER 1 exists to prevent."
    )


def test_without_as_of_date_a_future_split_DOES_change_historical_adjustment():
    """Negative control: proves the test above is actually meaningful --
    WITHOUT passing as_of_date, the old (pre-fix) behavior of adjusting
    against the dataset's last row is still available and DOES leak, so the
    fix is demonstrably doing something, not a no-op."""
    df_with_future_split = _fixture_with_a_split(split_date_idx=20, n=30)
    as_of = df_with_future_split.index[10]

    adjusted_no_as_of = normalize_provider_frame(df_with_future_split, "SPLIT_ADJUSTED", as_of_date=None)
    value_with_future_split_included = float(adjusted_no_as_of.loc[as_of, "Close"])

    df_truncated = df_with_future_split.loc[:as_of].copy()
    df_truncated["Stock Splits"] = 0.0
    adjusted_truncated = normalize_provider_frame(df_truncated, "SPLIT_ADJUSTED", as_of_date=None)
    value_without_future_split = float(adjusted_truncated.loc[as_of, "Close"])

    assert value_with_future_split_included != value_without_future_split, (
        "expected the no-as_of_date path to still exhibit look-ahead (proving the "
        "as_of_date fix above is the thing preventing it, not incidental)"
    )


def test_feature_frame_signal_at_D_is_invariant_to_a_split_dated_after_D():
    """End-to-end version of the same invariant through the full feature
    pipeline (EMA/alignment/etc.), not just the raw price series."""
    from ema_scanner.config import load_config
    from ema_scanner.features.regime import compute_market_regime
    from ema_scanner.strategy.signal_engine import build_stock_feature_frame

    n = 400
    dates = pd.bdate_range("2022-01-01", periods=n)
    rng = np.random.default_rng(7)
    pre_split_close = 200 + np.cumsum(rng.normal(0.05, 1.5, 350))
    split_idx = 350
    post_split_close = (pre_split_close[-1] / 2.0) + np.cumsum(rng.normal(0.05, 0.8, n - 350))
    raw_close = np.concatenate([pre_split_close, post_split_close])
    stock_splits = np.zeros(n)
    stock_splits[split_idx] = 2.0
    daily_with_split_info = pd.DataFrame({
        "Open": raw_close, "High": raw_close + 1, "Low": raw_close - 1, "Close": raw_close,
        "Volume": 100_000.0, "Stock Splits": stock_splits, "Dividends": 0.0,
    }, index=dates)

    as_of_date = dates[300]  # 50 sessions BEFORE the split
    adjusted_full = normalize_provider_frame(daily_with_split_info, "SPLIT_ADJUSTED", as_of_date=as_of_date)

    # Simulate the world as it genuinely looked on as_of_date: truncate the
    # raw data there and zero out the (not-yet-happened) split.
    truncated = daily_with_split_info.loc[:as_of_date].copy()
    truncated["Stock Splits"] = 0.0
    adjusted_truncated = normalize_provider_frame(truncated, "SPLIT_ADJUSTED", as_of_date=as_of_date)

    index_df = pd.DataFrame({"Close": np.linspace(20000, 21000, n)}, index=dates)
    cfg = load_config()

    regime_full = compute_market_regime(index_df)
    regime_trunc = compute_market_regime(index_df.loc[:as_of_date])

    feats_full = build_stock_feature_frame(adjusted_full.loc[:as_of_date], index_df["Close"].loc[:as_of_date], regime_full.loc[:as_of_date], cfg)
    feats_trunc = build_stock_feature_frame(adjusted_truncated, index_df["Close"].loc[:as_of_date], regime_trunc, cfg)

    check_date = dates[280]
    for col in ["EMA10", "EMA20", "EMA89", "EMA200", "Daily_State", "Cluster_Width_Pct"]:
        a, b = feats_full.loc[check_date, col], feats_trunc.loc[check_date, col]
        if pd.isna(a) and pd.isna(b):
            continue
        if isinstance(a, float):
            assert a == b or abs(a - b) < 1e-9, f"{col} at {check_date} differs due to a split dated AFTER as_of_date"
        else:
            assert a == b, f"{col} at {check_date} differs due to a split dated AFTER as_of_date"
