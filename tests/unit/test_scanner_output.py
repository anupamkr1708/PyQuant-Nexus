"""Scanner output semantics tests (Phase-2 Section 18 -- BLOCKER)."""

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import load_config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.reporting.scanner import build_scanner_row, build_scanner_tables
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from tests.fixtures.synthetic import make_synthetic_ohlcv


def _build_feats(seed):
    cfg = load_config()
    daily = make_synthetic_ohlcv(400, seed=seed)
    index_df = make_synthetic_ohlcv(400, seed=seed + 1)[["Close"]]
    regime = compute_market_regime(index_df)
    return build_stock_feature_frame(daily, index_df["Close"], regime, cfg)


def test_signal_close_is_not_labeled_entry_price_when_next_open():
    feats = _build_feats(10)
    cal = NSECalendar()
    row = build_scanner_row("AAA", None, feats, "PASS", cal, "next_open", eligible_for_signal=True)
    assert "Signal_Close" in row
    assert row["Execution_Model"] == "next_open"
    # There must be no field literally called "Entry_Price" implying today's close is the fill.
    assert "Entry_Price" not in row


def test_signals_table_only_contains_rows_with_actual_entry_trigger():
    rows = []
    cal = NSECalendar()
    for i in range(5):
        feats = _build_feats(20 + i)
        rows.append(build_scanner_row(f"SYM{i}", None, feats, "PASS", cal, "next_open", eligible_for_signal=True))

    # Guarantee at least one row with NO entry trigger at all, by forcing
    # every Entry* column false at the analysis date, so the "signals must
    # exclude non-triggered rows" assertion below cannot pass vacuously just
    # because the random fixture happened not to produce a non-signal row.
    no_trigger_feats = _build_feats(999).copy()
    entry_cols = [c for c in no_trigger_feats.columns if c.startswith("Entry")] + ["Any_Entry_Triggered"]
    for c in entry_cols:
        if c in no_trigger_feats.columns:
            no_trigger_feats.iloc[-1, no_trigger_feats.columns.get_loc(c)] = False
    rows.append(build_scanner_row("NO_TRIGGER_SYM", None, no_trigger_feats, "PASS", cal, "next_open", eligible_for_signal=True))

    tables = build_scanner_tables(rows)
    assert "signals" in tables and "candidates" in tables and "universe_diagnostics" in tables
    assert len(tables["universe_diagnostics"]) == 6
    for _, r in tables["signals"].iterrows():
        assert r["Entry_Models_Triggered"] not in (None, "")
    # The genuinely meaningful assertion (not just len <= len, which is
    # trivially true by construction): the deliberately-non-triggering
    # symbol must be ABSENT from signals and PRESENT in universe_diagnostics,
    # proving the filter actually excludes something rather than passing
    # everything through.
    assert "NO_TRIGGER_SYM" not in tables["signals"]["Symbol"].values
    assert "NO_TRIGGER_SYM" in tables["universe_diagnostics"]["Symbol"].values
    assert len(tables["signals"]) < len(tables["universe_diagnostics"])


def test_next_session_date_is_calendar_derived_even_when_price_is_unavailable():
    """BLOCKER 14 (Phase-3): Next_Session_Date must be resolvable from the
    calendar ALONE -- it must NOT be set to None just because tomorrow's
    price doesn't exist yet (the exact situation for every live EOD scan of
    the latest completed session, where "tomorrow" hasn't happened at all)."""
    cfg = load_config()
    daily = make_synthetic_ohlcv(400, seed=77)
    index_df = make_synthetic_ohlcv(400, seed=78)[["Close"]]
    regime = compute_market_regime(index_df)
    full_feats = build_stock_feature_frame(daily, index_df["Close"], regime, cfg)

    # Truncate the feature frame so the LAST row has genuinely no next-session
    # bar at all -- simulating a live scan of "today", where tomorrow's price
    # cannot exist yet.
    truncated_feats = full_feats.iloc[:-1]
    cal = NSECalendar()
    row = build_scanner_row("AAA", None, truncated_feats, "PASS", cal, "next_open", eligible_for_signal=True)

    assert row["Execution_Reference"] is None, "no future bar exists -- the price must correctly be unavailable"
    assert row["Next_Session_Date"] is not None, (
        "the NEXT SESSION DATE is a pure calendar fact and must be resolvable "
        "even when the next session's PRICE does not exist yet (BLOCKER 14)"
    )
    assert row["Next_Session_Date"] > truncated_feats.index[-1]


def test_next_session_date_uses_the_calendar_directly_not_the_execution_record():
    """Direct unit check on the mechanism: Next_Session_Date for next_open/
    next_close comes from `calendar.next_session`, independent of whether
    `resolve_execution_price` found an actual bar there."""
    cfg = load_config()
    daily = make_synthetic_ohlcv(400, seed=81)
    index_df = make_synthetic_ohlcv(400, seed=82)[["Close"]]
    regime = compute_market_regime(index_df)
    full_feats = build_stock_feature_frame(daily, index_df["Close"], regime, cfg)
    cal = NSECalendar()
    analysis_date = full_feats.index[-1]
    expected_next_session = cal.next_session(analysis_date)

    row = build_scanner_row("AAA", None, full_feats, "PASS", cal, "next_open", eligible_for_signal=True)
    assert row["Next_Session_Date"] == expected_next_session
    assert row["Execution_Reference"] is None  # no bar exists there yet


def test_empty_rows_produce_empty_tables_not_an_error():
    tables = build_scanner_tables([])
    assert tables["signals"].empty
    assert tables["universe_diagnostics"].empty
