"""Cluster metrics tests (brief Section 93 #6-9: cluster width, compression,
expansion, sequential crossover)."""

from ema_scanner.features.cluster import (
    compute_cluster_compression,
    compute_cluster_metrics,
    definition_A_sequential_crossover,
)
from ema_scanner.features.ema import compute_all_emas
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_cluster_width_is_never_negative():
    df = make_synthetic_ohlcv(400, seed=5)
    d = compute_all_emas(df)
    d = compute_cluster_metrics(d)
    assert (d["Cluster_Width_Pct"].dropna() >= 0).all()


def test_cluster_compression_flag_is_boolean_and_bounded():
    df = make_synthetic_ohlcv(400, seed=6)
    d = compute_all_emas(df)
    d = compute_cluster_metrics(d)
    d = compute_cluster_compression(d, lookback=100)
    valid = d["Cluster_Width_Percentile"].dropna()
    assert ((valid >= 0) & (valid <= 1)).all()


def test_definition_A_requires_all_three_crossovers_within_gap():
    from ema_scanner.features.crossover import compute_all_crossovers

    df = make_synthetic_ohlcv(300, seed=9)
    d = compute_all_emas(df)
    d = compute_all_crossovers(d)
    # Force a clean sequential-crossover scenario
    d["BULL_X_EMA10_EMA20"] = False
    d["BULL_X_EMA20_EMA89"] = False
    d["BULL_X_EMA89_EMA200"] = False
    d.iloc[10, d.columns.get_loc("BULL_X_EMA10_EMA20")] = True
    d.iloc[14, d.columns.get_loc("BULL_X_EMA20_EMA89")] = True
    d.iloc[18, d.columns.get_loc("BULL_X_EMA89_EMA200")] = True
    result = definition_A_sequential_crossover(d, max_gap=10)
    assert result.iloc[18] == True
    # Now push it out of range (gap > 10 between first and last)
    d["BULL_X_EMA10_EMA20"] = False
    d.iloc[0, d.columns.get_loc("BULL_X_EMA10_EMA20")] = True
    result2 = definition_A_sequential_crossover(d, max_gap=10)
    assert result2.iloc[18] == False
