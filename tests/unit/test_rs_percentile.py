"""Cross-sectional RS percentile tests (Phase-2 Section 10 -- BLOCKER)."""
import pandas as pd

from ema_scanner.features.relative_strength import compute_universe_rs_percentile


def test_percentile_uses_only_same_date_cross_section():
    dates = pd.bdate_range("2024-01-01", periods=5)
    frames = {
        "AAA": pd.DataFrame({"RS_60D": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=dates),
        "BBB": pd.DataFrame({"RS_60D": [5.0, 4.0, 3.0, 2.0, 1.0]}, index=dates),
        "CCC": pd.DataFrame({"RS_60D": [0.0, 0.0, 10.0, 0.0, 0.0]}, index=dates),
    }
    analysis_date = dates[2]
    result = compute_universe_rs_percentile(frames, analysis_date)
    # On date[2]: AAA=3.0, BBB=3.0, CCC=10.0 -> CCC should rank highest
    assert result["CCC"] == result.max()
    assert set(result.index) == {"AAA", "BBB", "CCC"}


def test_percentile_excludes_symbols_missing_data_on_that_date_not_fabricated():
    dates = pd.bdate_range("2024-01-01", periods=3)
    frames = {
        "AAA": pd.DataFrame({"RS_60D": [1.0, 2.0, 3.0]}, index=dates),
        "BBB": pd.DataFrame({"RS_60D": [1.0, float("nan"), 3.0]}, index=dates),
    }
    result = compute_universe_rs_percentile(frames, dates[1])
    assert "BBB" not in result.index
    assert "AAA" in result.index


def test_percentile_never_uses_a_different_or_future_date():
    dates = pd.bdate_range("2024-01-01", periods=5)
    frames = {
        "AAA": pd.DataFrame({"RS_60D": [1.0, 2.0, 3.0, 100.0, 5.0]}, index=dates),
    }
    result_at_early_date = compute_universe_rs_percentile(frames, dates[1])
    assert result_at_early_date["AAA"] == 100.0  # only value at dates[1] is used


def test_empty_universe_returns_empty_series():
    result = compute_universe_rs_percentile({}, pd.Timestamp("2024-01-01"))
    assert result.empty
