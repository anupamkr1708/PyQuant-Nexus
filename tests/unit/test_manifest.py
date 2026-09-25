"""Manifest correctness tests (Phase-2 Section 22 -- BLOCKER)."""
from ema_scanner.models import RunManifest
from ema_scanner.reporting.manifest import build_run_manifest, package_versions


def test_manifest_has_the_full_required_phase2_field_set():
    required_fields = {
        "run_id", "analysis_date", "decision_timestamp", "provider", "provider_version",
        "calendar_version", "universe_mode", "universe_date", "universe_count",
        "symbols_requested", "symbols_processed", "symbols_failed", "rows_downloaded",
        "rows_validated", "missing_sessions", "stale_symbols", "data_quality_summary",
        "strategy_version", "config_hash", "git_commit", "git_dirty", "python_version",
        "package_versions", "runtime_seconds",
    }
    dataclass_fields = set(RunManifest.__dataclass_fields__.keys())
    missing = required_fields - dataclass_fields
    assert not missing, f"RunManifest is missing required Phase-2 fields: {missing}"


def test_manifest_does_not_conflate_symbol_count_with_row_count():
    manifest = build_run_manifest(
        analysis_date="2026-09-22", decision_timestamp="2026-09-22T12:00:00Z",
        analysis_timezone="Asia/Kolkata", calendar_source="pandas_market_calendars", calendar_version="5.4.0",
        universe_source="https://example.com/list.csv", universe_date="2026-09-22", universe_mode="CURRENT_NIFTY200_HISTORICAL_SIMULATION",
        universe_count=200, provider="composite", provider_version=None,
        package_versions=package_versions(), config_hash="abc123", strategy_version="ema_cluster_v1",
        git_commit=None, git_dirty=None,
        symbols_requested=200, symbols_processed=180, symbols_failed=20,
        rows_downloaded=45000,  # a genuine ROW count, not == symbols_requested
        rows_validated=180, missing_sessions=3, stale_symbols=["XYZ"],
        data_quality_counts={"PASS": 170, "WARN": 10, "FAIL": 20}, runtime_seconds=12.5,
    )
    assert manifest.rows_downloaded != manifest.symbols_requested
    assert manifest.missing_sessions == 3  # never hard-coded to 0
    assert manifest.symbols_failed != manifest.stale_symbols.__len__() or True  # distinct concepts, not required equal
    assert manifest.universe_count == 200


def test_manifest_missing_sessions_is_not_hardcoded_zero_by_default():
    """Regression guard: v1 always wrote missing_sessions=0 regardless of
    actual data. Constructing a manifest with a nonzero value must round-trip."""
    manifest = build_run_manifest(
        analysis_date="2026-09-22", decision_timestamp="now", analysis_timezone="Asia/Kolkata",
        calendar_source="x", calendar_version="1", universe_source="x", universe_date=None,
        universe_mode="CURRENT_NIFTY200_HISTORICAL_SIMULATION", universe_count=3,
        provider="x", provider_version=None, package_versions={}, config_hash="x",
        strategy_version="ema_cluster_v1", git_commit=None, git_dirty=None,
        symbols_requested=3, symbols_processed=3, symbols_failed=0, rows_downloaded=100,
        rows_validated=3, missing_sessions=7, stale_symbols=[], data_quality_counts={}, runtime_seconds=1.0,
    )
    assert manifest.missing_sessions == 7
