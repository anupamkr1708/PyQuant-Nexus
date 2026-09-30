"""BLOCKER 11/13 (Phase-3): RANGE_COVERED vs RANGE_COMPLETE, and provenance."""
import tempfile

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.data.base import CompositeDataProvider, DataProvider, ProviderMetadata
from ema_scanner.data.cache import DataCache
from ema_scanner.data.repository import DataRepository


class _FakeProviderWithGap(DataProvider):
    name = "fake_gap"

    def get_daily_ohlcv(self, symbol, start_date, end_date):
        # Deterministic: Jan 1, 2, 3, [MISSING Jan 4 -- a Sunday, so actually
        # use a real weekday gap], Jan 5 -- construct explicitly with a
        # genuine mid-week trading-day hole.
        dates = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-05"])  # Jan 4 (Thursday) missing
        df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000}, index=dates)
        meta = ProviderMetadata(source="fake_gap", endpoint="x", retrieval_timestamp_utc="now",
                                 trade_date_coverage_start="2024-01-01", trade_date_coverage_end="2024-01-05",
                                 schema_version="v1")
        return df, meta


def test_range_covered_is_not_treated_as_range_complete():
    with tempfile.TemporaryDirectory() as tmp:
        cal = NSECalendar()
        repo = DataRepository(_FakeProviderWithGap(), DataCache(tmp), calendar=cal)
        df, diag = repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-01-05")
        assert pd.Timestamp("2024-01-04") not in df.index  # the actual gap
        assert "2024-01-04" in diag.internal_gap_sessions, (
            "an internal hole (Jan 1,2,3,[MISSING Jan 4],5) inside an otherwise-covered "
            "range must be detected, not silently treated as a complete cache hit"
        )
        assert diag.range_complete is False


def test_range_complete_when_no_gaps_present():
    with tempfile.TemporaryDirectory() as tmp:
        cal = NSECalendar()

        class _FullProvider(DataProvider):
            name = "full"
            def get_daily_ohlcv(self, symbol, start_date, end_date):
                dates = cal.valid_sessions(start_date, end_date)
                df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000}, index=dates)
                meta = ProviderMetadata("full", "x", "now", start_date, end_date, "v1")
                return df, meta

        repo = DataRepository(_FullProvider(), DataCache(tmp), calendar=cal)
        _df, diag = repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-01-31")
        assert diag.range_complete is True
        assert diag.internal_gap_sessions == []


def test_gap_check_is_skipped_without_a_calendar_not_silently_marked_complete():
    with tempfile.TemporaryDirectory() as tmp:
        repo = DataRepository(_FakeProviderWithGap(), DataCache(tmp), calendar=None)
        _df, diag = repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-01-05")
        assert diag.range_complete is None  # explicitly "not checked", never a false "True"


def test_composite_provider_provenance_records_the_concrete_source():
    with tempfile.TemporaryDirectory() as tmp:
        class _Primary(DataProvider):
            name = "primary_x"
            def get_daily_ohlcv(self, symbol, start_date, end_date):
                dates = pd.bdate_range(start_date, end_date)
                df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=dates)
                return df, ProviderMetadata("primary_x", "x", "now", start_date, end_date, "v1")

        composite = CompositeDataProvider([_Primary()])
        repo = DataRepository(composite, DataCache(tmp))
        _df, diag = repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-01-31")
        assert diag.resolved_source == "primary_x"
        assert diag.resolved_source != "composite"
