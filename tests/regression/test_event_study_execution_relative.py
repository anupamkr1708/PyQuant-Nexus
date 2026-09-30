"""BLOCKER 4/5 (Phase-3): event study must be execution-relative, not
signal-date-relative. Deterministic fixtures with known, hand-computed
expected values -- not random/synthetic data.
"""
import numpy as np
import pandas as pd

from ema_scanner.research.event_study import event_study_forward_returns


def _deterministic_price_path():
    """Known Close/High/Low values at each position so expected Fwd_Ret/MFE/MAE
    can be hand-computed exactly. Position 5 = signal date, position 6 =
    execution date (next session)."""
    dates = pd.bdate_range("2023-01-02", periods=15)  # avoid weekends for a clean 1-session-per-day mapping
    close = np.array([100, 101, 102, 103, 104, 105, 110, 112, 108, 115, 120, 118, 125, 130, 128], dtype=float)
    high = close + 2.0
    low = close - 2.0
    df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close}, index=dates)
    return df


def test_next_open_h1_is_execution_day_close_not_signal_day_plus_one():
    """BLOCKER 4: for NEXT_OPEN, H=1 must be the EXECUTION day's own close
    (entry at that day's Open), not signal_date+1's close."""
    df = _deterministic_price_path()
    signal_date = df.index[5]
    execution_date = df.index[6]  # next session -- entry at its Open == Close[6] == 110 (Open==Close in this fixture)
    entry_price = float(df.loc[execution_date, "Open"])
    events = pd.DataFrame([{"Signal_Date": signal_date, "Execution_Date": execution_date, "Execution_Price": entry_price}])

    result = event_study_forward_returns(df, events, entry_stage="OPEN", horizons=(1, 2))
    row = result.iloc[0]

    expected_h1 = (float(df["Close"].iloc[6]) - entry_price) / entry_price * 100.0  # SAME session (execution day) close
    expected_h2 = (float(df["Close"].iloc[7]) - entry_price) / entry_price * 100.0  # 1 session after execution
    assert row["Fwd_Ret_1D"] == expected_h1
    assert row["Fwd_Ret_2D"] == expected_h2
    # Sanity: signal and execution dates are genuinely different here, so this
    # test could not pass by coincidence if the code were still anchoring on
    # Signal_Date instead of Execution_Date.
    assert execution_date != signal_date


def test_next_close_h1_is_the_following_sessions_close():
    """BLOCKER 4: for NEXT_CLOSE, H=1 must be the session AFTER execution's
    close -- never zero return at the execution close itself."""
    df = _deterministic_price_path()
    signal_date = df.index[5]
    execution_date = df.index[6]
    entry_price = float(df.loc[execution_date, "Close"])  # entry AT that day's close
    events = pd.DataFrame([{"Signal_Date": signal_date, "Execution_Date": execution_date, "Execution_Price": entry_price}])

    result = event_study_forward_returns(df, events, entry_stage="CLOSE", horizons=(1,))
    row = result.iloc[0]

    expected_h1 = (float(df["Close"].iloc[7]) - entry_price) / entry_price * 100.0  # FOLLOWING session's close
    assert row["Fwd_Ret_1D"] == expected_h1
    assert row["Fwd_Ret_1D"] != 0.0, "H=1 must not be a trivial zero return at the execution close itself"


def test_same_close_h1_is_the_following_sessions_close():
    """BLOCKER 4: same_close behaves like next_close for horizon purposes --
    entry occurs at the signal day's own close, so H=1 is the next session."""
    df = _deterministic_price_path()
    signal_date = df.index[5]
    execution_date = signal_date  # same_close: execution_date == signal_date
    entry_price = float(df.loc[execution_date, "Close"])
    events = pd.DataFrame([{"Signal_Date": signal_date, "Execution_Date": execution_date, "Execution_Price": entry_price}])

    result = event_study_forward_returns(df, events, entry_stage="CLOSE", horizons=(1,))
    row = result.iloc[0]
    expected_h1 = (float(df["Close"].iloc[6]) - entry_price) / entry_price * 100.0
    assert row["Fwd_Ret_1D"] == expected_h1


def test_mfe_mae_excludes_pre_entry_intraday_for_close_stage():
    """BLOCKER 5: for NEXT_CLOSE/SAME_CLOSE, the execution day's OWN
    High/Low (which occurred BEFORE the close-price entry) must be excluded
    from MFE/MAE."""
    df = _deterministic_price_path()
    execution_date = df.index[6]
    entry_price = float(df.loc[execution_date, "Close"])
    events = pd.DataFrame([{"Signal_Date": df.index[5], "Execution_Date": execution_date, "Execution_Price": entry_price}])

    result = event_study_forward_returns(df, events, entry_stage="CLOSE", horizons=(3,))
    row = result.iloc[0]
    # The execution day's own High (112.0 at position 6) must NOT be
    # reflected in MFE -- only positions 7,8,9 (max_h=3 sessions after).
    execution_day_high_excursion_pct = (float(df["High"].iloc[6]) - entry_price) / entry_price * 100.0
    post_entry_only_max = float(df["High"].iloc[7:10].max())
    expected_mfe = (post_entry_only_max - entry_price) / entry_price * 100.0
    assert row["MFE_Pct"] == expected_mfe
    assert row["MFE_Pct"] != execution_day_high_excursion_pct or expected_mfe == execution_day_high_excursion_pct


def test_mfe_mae_includes_execution_day_for_open_stage():
    """BLOCKER 5: for NEXT_OPEN, the execution day's own High/Low ARE valid
    post-entry observations (entry at that day's Open)."""
    df = _deterministic_price_path()
    execution_date = df.index[6]
    entry_price = float(df.loc[execution_date, "Open"])
    events = pd.DataFrame([{"Signal_Date": df.index[5], "Execution_Date": execution_date, "Execution_Price": entry_price}])

    result = event_study_forward_returns(df, events, entry_stage="OPEN", horizons=(3,))
    row = result.iloc[0]
    # Window is positions 6,7,8 (max_h=3, starting AT execution day for OPEN stage).
    window_high_max = float(df["High"].iloc[6:9].max())
    expected_mfe = (window_high_max - entry_price) / entry_price * 100.0
    assert row["MFE_Pct"] == expected_mfe


def test_missing_execution_date_produces_no_row_not_a_fabricated_one():
    df = _deterministic_price_path()
    events = pd.DataFrame([{"Signal_Date": df.index[5], "Execution_Date": pd.Timestamp("2099-01-01"), "Execution_Price": 100.0}])
    result = event_study_forward_returns(df, events, entry_stage="OPEN")
    assert result.empty
