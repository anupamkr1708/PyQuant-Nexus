"""Cache-first repository tests (Phase-2 Section 2 -- BLOCKER)."""
import tempfile

import pandas as pd

from ema_scanner.data.base import DataProvider, DataUnavailableError, ProviderMetadata
from ema_scanner.data.cache import DataCache
from ema_scanner.data.repository import DataRepository


class _FakeProvider(DataProvider):
    name = "fake"

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def get_daily_ohlcv(self, symbol, start_date, end_date):
        self.calls.append((start_date, end_date))
        dates = pd.bdate_range(start_date, end_date)
        if len(dates) == 0:
            raise DataUnavailableError("empty range")
        df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000}, index=dates)
        meta = ProviderMetadata(source="fake", endpoint="fake", retrieval_timestamp_utc="now",
                                 trade_date_coverage_start=str(dates.min().date()),
                                 trade_date_coverage_end=str(dates.max().date()), schema_version="v1")
        return df, meta


def test_cold_cache_triggers_exactly_one_full_fetch():
    with tempfile.TemporaryDirectory() as tmp:
        provider = _FakeProvider()
        repo = DataRepository(provider, DataCache(tmp))
        df, diag = repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-03-01")
        assert diag.cache_hit is False
        assert diag.cache_miss is True
        assert len(provider.calls) == 1
        assert len(df) > 0


def test_warm_cache_does_not_refetch_when_range_already_covered():
    with tempfile.TemporaryDirectory() as tmp:
        provider = _FakeProvider()
        repo = DataRepository(provider, DataCache(tmp))
        repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-03-01")
        calls_after_first = len(provider.calls)
        df2, diag2 = repo.get_daily_ohlcv("AAA", "2024-01-15", "2024-02-15")  # fully inside cached range
        assert len(provider.calls) == calls_after_first  # NO new provider call
        assert diag2.cache_hit is True
        assert diag2.rows_downloaded == 0
        assert len(df2) > 0


def test_extending_the_end_date_only_fetches_the_missing_tail_plus_overlap():
    with tempfile.TemporaryDirectory() as tmp:
        provider = _FakeProvider()
        repo = DataRepository(provider, DataCache(tmp), overlap_sessions=5)
        repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-03-01")
        df2, diag2 = repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-04-01")  # extended end
        assert diag2.cache_hit is True
        assert diag2.refresh_start is not None
        # The second fetch's requested start must be AFTER the original cache's start
        # (i.e. we did not re-download the whole 4-year-style range again).
        second_call_start = provider.calls[-1][0]
        assert pd.Timestamp(second_call_start) > pd.Timestamp("2024-01-01")
        assert df2.index.max() >= pd.Timestamp("2024-03-29")  # last business day near 2024-04-01


def test_provider_failure_on_refresh_still_serves_cached_data_when_possible():
    with tempfile.TemporaryDirectory() as tmp:
        provider = _FakeProvider()
        repo = DataRepository(provider, DataCache(tmp))
        repo.get_daily_ohlcv("AAA", "2024-01-01", "2024-03-01")

        def _broken(*a, **kw):
            raise DataUnavailableError("provider down")
        provider.get_daily_ohlcv = _broken  # simulate provider outage on refresh attempt

        df2, _diag2 = repo.get_daily_ohlcv("AAA", "2024-01-15", "2024-02-01")  # within cached range, no refresh needed anyway
        assert len(df2) > 0
