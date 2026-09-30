"""BLOCKER 27 (Phase-3): research commands must never silently skip stocks."""
import pandas as pd

from ema_scanner.research.data_audit import build_research_data_audit


def test_excluded_symbols_are_reported_with_a_reason_not_silently_dropped():
    requested = ["AAA", "BBB", "CCC"]
    eligible = {"AAA": pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.bdate_range("2024-01-01", periods=2))}
    exclusions = {"BBB": "data_fetch: DATA_UNAVAILABLE", "CCC": "quality_gate: FAIL"}
    audit = build_research_data_audit(requested, eligible, exclusions)

    assert audit.requested_symbols == 3
    assert audit.eligible_symbols == 1
    assert audit.excluded_symbols == 2
    reasons = {e.symbol: e.reason for e in audit.entries if e.status == "EXCLUDED"}
    assert reasons["BBB"].startswith("data_fetch")
    assert reasons["CCC"].startswith("quality_gate")


def test_summary_line_discloses_the_eligible_fraction():
    requested = ["A", "B"]
    eligible = {"A": pd.DataFrame({"Close": [1.0]}, index=pd.bdate_range("2024-01-01", periods=1))}
    audit = build_research_data_audit(requested, eligible, {"B": "excluded"})
    summary = audit.summary_line()
    assert "1 eligible" in summary
    assert "1 excluded" in summary
    assert "2" in summary  # requested count


def test_no_symbols_requested_produces_a_valid_empty_report():
    audit = build_research_data_audit([], {}, {})
    assert audit.requested_symbols == 0
    assert audit.eligible_symbols == 0
    df = audit.to_dataframe()
    assert df.empty
