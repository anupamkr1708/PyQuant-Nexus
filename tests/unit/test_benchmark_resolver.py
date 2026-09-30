"""BLOCKER 7 (Phase-3): benchmark configuration must actually work."""
import pytest

from ema_scanner.config import RegimeConfig
from ema_scanner.features.regime import BenchmarkResolutionError, resolve_benchmark


def test_nifty50_resolves_to_verified_ticker():
    cfg = RegimeConfig(benchmark="NIFTY50")
    resolved = resolve_benchmark(cfg)
    assert resolved.symbol == "^NSEI"


def test_nifty200_refuses_to_guess_an_unverified_ticker():
    cfg = RegimeConfig(benchmark="NIFTY200")
    with pytest.raises(BenchmarkResolutionError, match="no verified Yahoo Finance ticker"):
        resolve_benchmark(cfg)


def test_custom_benchmark_requires_a_symbol():
    cfg = RegimeConfig(benchmark="CUSTOM", custom_benchmark_symbol=None)
    with pytest.raises(BenchmarkResolutionError, match="custom_benchmark_symbol"):
        resolve_benchmark(cfg)


def test_custom_benchmark_with_symbol_resolves():
    cfg = RegimeConfig(benchmark="CUSTOM", custom_benchmark_symbol="^BSESN")
    resolved = resolve_benchmark(cfg)
    assert resolved.symbol == "^BSESN"


def test_changing_benchmark_config_changes_the_resolved_symbol():
    """The core BLOCKER 7 assertion: config actually controls the outcome."""
    default_resolved = resolve_benchmark(RegimeConfig())
    custom_resolved = resolve_benchmark(RegimeConfig(benchmark="CUSTOM", custom_benchmark_symbol="MYINDEX.NS"))
    assert default_resolved.symbol != custom_resolved.symbol


def test_configured_regime_ema_periods_actually_change_output():
    """The second half of BLOCKER 7: index_ema_* config must actually reach
    compute_market_regime, not be silently ignored in favor of the
    function's own hard-coded defaults."""
    import numpy as np
    import pandas as pd

    from ema_scanner.features.regime import compute_market_regime

    dates = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(5)
    close = 20000 + np.cumsum(rng.normal(2, 40, 400))
    index_df = pd.DataFrame({"Close": close}, index=dates)

    default_regime = compute_market_regime(index_df, ema_fast=20, ema_medium=50, ema_structural=89, ema_long=200)
    custom_regime = compute_market_regime(index_df, ema_fast=5, ema_medium=15, ema_structural=40, ema_long=100)

    assert not default_regime["Index_EMA200"].dropna().equals(custom_regime["Index_EMA200"].dropna())
