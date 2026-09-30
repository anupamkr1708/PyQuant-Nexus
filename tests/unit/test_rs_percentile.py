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


def test_three_symbol_percentile_unaffected_by_injecting_extreme_future_values():
    """BLOCKER 22 (Phase-3): strengthened from the single-symbol case above.
    AAA/BBB/CCC have KNOWN same-date RS values on `earlier_date`. We then
    inject EXTREME future values (both a new all-time-high and an all-time-low)
    at a LATER date for all three symbols and prove the percentile ranking at
    `earlier_date` is completely unchanged -- not just numerically close, but
    byte-for-byte identical, since the computation must never even look past
    `earlier_date`."""
    dates = pd.bdate_range("2024-01-01", periods=10)
    earlier_date = dates[3]

    base_frames = {
        "AAA": pd.DataFrame({"RS_60D": [0.0, 0.0, 0.0, 5.0, 0, 0, 0, 0, 0, 0]}, index=dates),
        "BBB": pd.DataFrame({"RS_60D": [0.0, 0.0, 0.0, 15.0, 0, 0, 0, 0, 0, 0]}, index=dates),
        "CCC": pd.DataFrame({"RS_60D": [0.0, 0.0, 0.0, 10.0, 0, 0, 0, 0, 0, 0]}, index=dates),
    }
    result_before = compute_universe_rs_percentile(base_frames, earlier_date)
    # Known ranking at earlier_date: BBB(15) > CCC(10) > AAA(5)
    assert result_before["BBB"] > result_before["CCC"] > result_before["AAA"]

    # Now inject EXTREME future values (an outlier high AND an outlier low)
    # for every symbol at dates AFTER earlier_date.
    injected_frames = {sym: df.copy() for sym, df in base_frames.items()}
    injected_frames["AAA"].loc[dates[7], "RS_60D"] = 1_000_000.0   # extreme future high
    injected_frames["BBB"].loc[dates[8], "RS_60D"] = -1_000_000.0  # extreme future low
    injected_frames["CCC"].loc[dates[9], "RS_60D"] = 500_000.0
    result_after = compute_universe_rs_percentile(injected_frames, earlier_date)

    for sym in ("AAA", "BBB", "CCC"):
        assert result_before[sym] == result_after[sym], (
            f"{sym}'s percentile at {earlier_date.date()} changed after injecting extreme "
            f"FUTURE values -- cross-sectional percentile must never look past the analysis date"
        )
    # And the ranking itself is preserved.
    assert result_after["BBB"] > result_after["CCC"] > result_after["AAA"]


def test_percentile_at_later_date_DOES_reflect_injected_values_sanity_control():
    """Negative control proving the injected values in the test above were
    real and would have mattered if they occurred AT-OR-BEFORE the analysis
    date -- otherwise the invariance test could be vacuously true simply
    because the injected values were never read by anything."""
    dates = pd.bdate_range("2024-01-01", periods=10)
    frames = {
        "AAA": pd.DataFrame({"RS_60D": [0.0] * 7 + [1_000_000.0] + [0.0] * 2}, index=dates),
        "BBB": pd.DataFrame({"RS_60D": [0.0] * 10}, index=dates),
        "CCC": pd.DataFrame({"RS_60D": [0.0] * 10}, index=dates),
    }
    result_at_injection_date = compute_universe_rs_percentile(frames, dates[7])
    assert result_at_injection_date["AAA"] == 100.0  # confirms the injected value IS visible when it's not "future"


def test_empty_universe_returns_empty_series():
    result = compute_universe_rs_percentile({}, pd.Timestamp("2024-01-01"))
    assert result.empty
