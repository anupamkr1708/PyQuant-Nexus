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
    tables = build_scanner_tables(rows)
    assert "signals" in tables and "candidates" in tables and "universe_diagnostics" in tables
    assert len(tables["universe_diagnostics"]) == 5
    for _, r in tables["signals"].iterrows():
        assert r["Entry_Models_Triggered"] not in (None, "")
    # signals count must NEVER just equal "how many rows were processed"
    assert len(tables["signals"]) <= len(tables["universe_diagnostics"])


def test_empty_rows_produce_empty_tables_not_an_error():
    tables = build_scanner_tables([])
    assert tables["signals"].empty
    assert tables["universe_diagnostics"].empty
