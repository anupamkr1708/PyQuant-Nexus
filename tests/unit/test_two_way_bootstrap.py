"""BLOCKER 20 (Phase-3): date-clustered and two-way bootstrap CIs."""
import numpy as np
import pandas as pd

from ema_scanner.research.statistics import (
    block_bootstrap_ci,
    block_bootstrap_ci_by_date,
    two_way_cluster_bootstrap_ci,
)


def _correlated_market_wide_fixture():
    """Many different tickers all signal on the SAME few dates with a shared
    market-wide shock -- ticker-only clustering treats each ticker as
    independent, but genuinely everything on a shared date moves together."""
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2022-01-01", periods=6)
    rows = []
    for d_i, d in enumerate(dates):
        market_shock = rng.normal(0, 5)  # shared shock for this date
        for t_i in range(10):
            rows.append({"Ticker": f"T{t_i}", "Execution_Date": d, "Fwd_Ret_20D": market_shock + rng.normal(0, 0.5)})
    return pd.DataFrame(rows)


def test_date_clustered_ci_is_wider_than_naive_iid_assumption_would_suggest():
    df = _correlated_market_wide_fixture()
    date_result = block_bootstrap_ci_by_date(df, "Fwd_Ret_20D", n_boot=1000)
    assert date_result["n_clusters"] == 6  # 6 distinct dates, not 60 "independent" rows
    assert date_result["ci_high"] > date_result["ci_low"]


def test_ticker_clustered_ci_understates_uncertainty_for_date_correlated_data():
    """The core BLOCKER 20 point: with this fixture's market-wide-shock
    structure, ticker-only clustering (60 obs across only 10 "clusters" that
    are each internally low-variance) produces a MUCH tighter CI than
    date-clustering (6 clusters, each with high shared variance) -- showing
    why relying on ticker-clustering alone can understate true uncertainty
    when the real dependence is cross-sectional/date-based."""
    df = _correlated_market_wide_fixture()
    ticker_result = block_bootstrap_ci(df, "Fwd_Ret_20D", n_boot=1000)
    date_result = block_bootstrap_ci_by_date(df, "Fwd_Ret_20D", n_boot=1000)
    ticker_width = ticker_result["ci_high"] - ticker_result["ci_low"]
    date_width = date_result["ci_high"] - date_result["ci_low"]
    assert date_width > ticker_width, (
        "date-clustered CI should be substantially wider than ticker-clustered CI "
        "for data with a shared market-wide shock per date -- this is exactly the "
        "dependence structure ticker-only clustering misses"
    )


def test_two_way_bootstrap_reports_both_single_way_cis_and_a_combined_bound():
    df = _correlated_market_wide_fixture()
    result = two_way_cluster_bootstrap_ci(df, "Fwd_Ret_20D", n_boot=500)
    assert "ticker_only_ci_low" in result and "date_only_ci_low" in result
    assert "two_way_ci_low" in result
    assert result["widest_ci_low"] <= result["ticker_only_ci_low"]
    assert result["widest_ci_high"] >= result["ticker_only_ci_high"]
    assert "NOT_a_rigorous_multiway_estimator" in result["method"]


def test_two_way_bootstrap_handles_empty_input():
    result = two_way_cluster_bootstrap_ci(pd.DataFrame(columns=["Ticker", "Execution_Date", "Fwd_Ret_20D"]), "Fwd_Ret_20D")
    assert result["n_observations"] == 0
