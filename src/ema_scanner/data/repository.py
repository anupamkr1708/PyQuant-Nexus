"""Cache-first data repository (Phase-2 Section 2 -- BLOCKER).

**Bug fixed:** v1 had a `DataCache` capable of atomic, deduplicated writes,
but the operational scan/research code paths called `provider.get_daily_ohlcv`
directly every time and only wrote the *result* to cache afterward -- i.e. it
re-downloaded the full requested range from the provider on every run
regardless of what was already cached. This module makes the cache the first
thing consulted, and only fetches the genuinely missing range (+ a configured
overlap buffer, since vendor corrections can revise recent bars -- brief
Section 18) from the provider.

Flow implemented exactly as specified:

    request -> inspect local cache -> determine missing sessions
      -> download missing range + overlap -> normalize -> validate -> merge
      -> deduplicate -> atomically persist -> return dataset

Diagnostics are returned alongside the data (not just logged) so callers can
put them in the run manifest, per Phase-2 Section 2's exact field list.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ema_scanner.data.base import DataProvider, DataUnavailableError
from ema_scanner.data.cache import DataCache
from ema_scanner.data.normalization import normalize_provider_frame


@dataclass
class RefreshDiagnostics:
    symbol: str
    cache_hit: bool
    cache_miss: bool
    refresh_start: str | None
    refresh_end: str | None
    overlap_sessions: int
    previous_latest_session: str | None
    new_latest_session: str | None
    rows_before: int
    rows_after: int
    rows_downloaded: int


class DataRepository:
    """Cache-first wrapper around a `DataProvider`. One repository per
    (provider, price_mode) pair is the intended usage."""

    def __init__(self, provider: DataProvider, cache: DataCache, price_mode: str = "SPLIT_ADJUSTED", overlap_sessions: int = 10):
        self.provider = provider
        self.cache = cache
        self.price_mode = price_mode
        self.overlap_sessions = overlap_sessions

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, RefreshDiagnostics]:
        start_ts, end_ts = pd.Timestamp(start_date), pd.Timestamp(end_date)
        cached, _cache_meta = self.cache.read(self.provider.name, symbol, adjustment_mode=self.price_mode)

        if cached is None or cached.empty:
            # Full cold fetch: nothing cached yet for this key.
            raw, meta = self.provider.get_daily_ohlcv(symbol, start_date, end_date)
            normalized = normalize_provider_frame(raw, self.price_mode)
            merged = self.cache.write_merged(self.provider.name, symbol, normalized, meta, adjustment_mode=self.price_mode)
            diag = RefreshDiagnostics(
                symbol=symbol, cache_hit=False, cache_miss=True,
                refresh_start=start_date, refresh_end=end_date, overlap_sessions=0,
                previous_latest_session=None, new_latest_session=str(merged.index.max().date()),
                rows_before=0, rows_after=len(merged), rows_downloaded=len(normalized),
            )
            return merged.loc[start_ts:end_ts], diag

        # Cache exists: determine what's actually missing, with an overlap
        # buffer applied to the RE-FETCH boundary (not to what we trust as
        # already-final), per brief Section 18.
        previous_latest = str(cached.index.max().date())
        rows_before = len(cached)
        cached_start, cached_end = cached.index.min(), cached.index.max()
        needs_refresh = False
        refresh_start_ts = start_ts

        if end_ts > cached_end:
            # New sessions needed at the tail, re-pulling `overlap_sessions`
            # of already-cached recent bars too (vendor corrections).
            refresh_start_ts = max(start_ts, cached_end - pd.Timedelta(days=int(self.overlap_sessions * 1.5) + 3))
            needs_refresh = True
        if start_ts < cached_start:
            # Older history requested than what's cached -- must backfill.
            refresh_start_ts = min(refresh_start_ts, start_ts)
            needs_refresh = True

        if not needs_refresh:
            diag = RefreshDiagnostics(
                symbol=symbol, cache_hit=True, cache_miss=False,
                refresh_start=None, refresh_end=None, overlap_sessions=self.overlap_sessions,
                previous_latest_session=previous_latest, new_latest_session=previous_latest,
                rows_before=rows_before, rows_after=rows_before, rows_downloaded=0,
            )
            return cached.loc[start_ts:end_ts], diag

        try:
            raw, meta = self.provider.get_daily_ohlcv(symbol, str(refresh_start_ts.date()), end_date)
        except DataUnavailableError:
            if start_ts >= cached_start:  # can still serve from cache even if refresh failed
                diag = RefreshDiagnostics(
                    symbol=symbol, cache_hit=True, cache_miss=False,
                    refresh_start=str(refresh_start_ts.date()), refresh_end=end_date,
                    overlap_sessions=self.overlap_sessions, previous_latest_session=previous_latest,
                    new_latest_session=previous_latest, rows_before=rows_before, rows_after=rows_before,
                    rows_downloaded=0,
                )
                return cached.loc[start_ts:end_ts], diag
            raise

        normalized = normalize_provider_frame(raw, self.price_mode)
        merged = self.cache.write_merged(self.provider.name, symbol, normalized, meta, adjustment_mode=self.price_mode)
        diag = RefreshDiagnostics(
            symbol=symbol, cache_hit=True, cache_miss=False,
            refresh_start=str(refresh_start_ts.date()), refresh_end=end_date,
            overlap_sessions=self.overlap_sessions, previous_latest_session=previous_latest,
            new_latest_session=str(merged.index.max().date()),
            rows_before=rows_before, rows_after=len(merged), rows_downloaded=len(normalized),
        )
        return merged.loc[start_ts:end_ts], diag
