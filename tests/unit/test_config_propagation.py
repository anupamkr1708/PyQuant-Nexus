"""BLOCKER 25/26 (Phase-3): previously-buried magic numbers must actually be
config-driven, and config must actually propagate through the pipeline.
"""

from ema_scanner.config import load_config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_cluster_slope_lookback_config_changes_output():
    cfg_a = load_config()
    cfg_a.strategy.cluster.width_slope_lookback_days = 5
    cfg_b = load_config()
    cfg_b.strategy.cluster.width_slope_lookback_days = 20

    daily = make_synthetic_ohlcv(400, seed=200)
    index_df = make_synthetic_ohlcv(400, seed=201)[["Close"]]
    regime_a = compute_market_regime(index_df)
    regime_b = compute_market_regime(index_df)

    feats_a = build_stock_feature_frame(daily, index_df["Close"], regime_a, cfg_a)
    feats_b = build_stock_feature_frame(daily, index_df["Close"], regime_b, cfg_b)
    assert not feats_a["Cluster_Width_Slope"].dropna().equals(feats_b["Cluster_Width_Slope"].dropna())


def test_ema_slope_lookback_config_changes_output():
    cfg_a = load_config()
    cfg_a.strategy.volatility.ema_slope_lookback_days = 10
    cfg_b = load_config()
    cfg_b.strategy.volatility.ema_slope_lookback_days = 30

    daily = make_synthetic_ohlcv(400, seed=210)
    index_df = make_synthetic_ohlcv(400, seed=211)[["Close"]]
    regime = compute_market_regime(index_df)
    feats_a = build_stock_feature_frame(daily, index_df["Close"], regime, cfg_a)
    feats_b = build_stock_feature_frame(daily, index_df["Close"], regime, cfg_b)
    # Column name itself encodes the lookback (EMA20_Slope_Pct_{k}D) -- proves
    # the config value reached the computation rather than being ignored.
    assert "EMA20_Slope_Pct_10D" in feats_a.columns
    assert "EMA20_Slope_Pct_30D" in feats_b.columns
    assert "EMA20_Slope_Pct_30D" not in feats_a.columns


def test_liquidity_volume_window_config_changes_output():
    cfg_a = load_config()
    cfg_a.strategy.liquidity.volume_window_fast_days = 20
    cfg_b = load_config()
    cfg_b.strategy.liquidity.volume_window_fast_days = 60

    daily = make_synthetic_ohlcv(400, seed=220)
    index_df = make_synthetic_ohlcv(400, seed=221)[["Close"]]
    regime = compute_market_regime(index_df)
    feats_a = build_stock_feature_frame(daily, index_df["Close"], regime, cfg_a)
    feats_b = build_stock_feature_frame(daily, index_df["Close"], regime, cfg_b)
    assert not feats_a["Average_Daily_Traded_Value"].dropna().equals(feats_b["Average_Daily_Traded_Value"].dropna())


def test_backtest_config_actually_propagates_to_the_engine():
    """BLOCKER 26: research.backtest.* config fields must reach
    run_portfolio_backtest, not just exist unused."""
    from ema_scanner.calendar.nse import NSECalendar
    from ema_scanner.research.backtest import run_portfolio_backtest

    cfg = load_config()
    cfg.research.backtest.initial_capital = 42_000.0
    cfg.research.backtest.max_concurrent_positions = 1

    daily = make_synthetic_ohlcv(300, seed=230, drift=0.05)
    index_df = make_synthetic_ohlcv(300, seed=231)[["Close"]]
    regime = compute_market_regime(index_df)
    feats = build_stock_feature_frame(daily, index_df["Close"], regime, cfg)
    result = run_portfolio_backtest({"SYM": feats}, NSECalendar(), cfg)
    assert result.config_summary["initial_capital"] == 42_000.0
    assert result.config_summary["max_concurrent_positions"] == 1
