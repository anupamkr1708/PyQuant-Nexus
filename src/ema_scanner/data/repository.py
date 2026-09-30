"""Cache-first data repository (Phase-2 Section 2; Phase-3 BLOCKERS 1, 2, 11, 13).

Flow implemented exactly as specified:

    request -> inspect local RAW cache -> determine missing sessions
      -> download missing RAW range + overlap -> merge (raw) -> deduplicate
      -> atomically persist (raw) -> POINT-IN-TIME normalize (as_of=end_date)
      -> return dataset

**BLOCKER 2 fix:** the cache stores RAW provider columns (including
`Dividends`/`Stock Splits`/`AdjClose`), never only the derived, already-
adjusted OHLCV. Normalization (`data/normalization.py::normalize_provider_frame`)
now happens HERE, fresh, on every call, using `as_of_date=end_date` -- so
point-in-time correctness (BLOCKER 1) is enforced automatically for every
caller, and the durable cache is never the ONLY place the corporate-action
history lives.

**BLOCKER 11 fix:** `RANGE_COVERED` (the requested date span falls inside the
cache's [min, max]) is no longer treated as equivalent to `RANGE_COMPLETE`
(every expected trading session within that span is actually present). A
gap-check against the exchange calendar now runs even on a "cache hit", and
missing internal sessions are surfaced in `RefreshDiagnostics` rather than
silently ignored. If the gap-check finds missing sessions, this repository
still does NOT invent data to fill them (only the provider can supply real
bars) -- it reports `internal_gap_sessions` so callers (validate_ohlc, the
scan/backtest commands) can decide how to react, consistent with brief
Section 19 ("mark, don't silently delete/fabricate").

**BLOCKER 13 fix:** when the caller's provider is a `CompositeDataProvider`,
`RefreshDiagnostics.resolved_source` records the actual concrete provider
name that served THIS fetch (primary vs. secondary), not the string
`"composite"` -- so the run manifest can identify the real data source per
symbol/segment rather than an opaque wrapper name.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.data.base import CompositeDataProvider, DataProvider, DataUnavailableError
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
    resolved_source: str | None = None
    internal_gap_sessions: list[str] = field(default_factory=list)
    range_complete: bool | None = None  # None = not checked (no calendar supplied)


class DataRepository:
    """Cache-first wrapper around a `DataProvider`. One repository per
    (provider, price_mode) pair is the intended usage."""

    def __init__(
        self, provider: DataProvider, cache: DataCache, price_mode: str = "SPLIT_ADJUSTED",
        overlap_sessions: int = 10, calendar: NSECalendar | None = None,
    ):
        self.provider = provider
        self.cache = cache
        self.price_mode = price_mode
        self.overlap_sessions = overlap_sessions
        self.calendar = calendar  # optional: enables BLOCKER 11's internal-gap check

    def _resolved_source_for(self, raw_provider_name: str) -> str:
        """BLOCKER 13: never key provenance solely as 'composite'."""
        if isinstance(self.provider, CompositeDataProvider):
            return raw_provider_name  # the concrete provider that actually returned data
        return self.provider.name

    def _check_internal_gaps(self, df: pd.DataFrame, start_ts, end_ts) -> list[str]:
        if self.calendar is None or df.empty:
            return []
        expected = self.calendar.valid_sessions(max(start_ts, df.index.min()), min(end_ts, df.index.max()))
        missing = sorted(set(expected) - set(df.index))
        return [str(d.date()) for d in missing]

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, RefreshDiagnostics]:
        start_ts, end_ts = pd.Timestamp(start_date), pd.Timestamp(end_date)
        cached_raw, _cache_meta = self.cache.read(self.provider.name, symbol)

        if cached_raw is None or cached_raw.empty:
            raw, meta = self.provider.get_daily_ohlcv(symbol, start_date, end_date)
            merged_raw = self.cache.write_merged(self.provider.name, symbol, raw, meta)
            normalized = normalize_provider_frame(merged_raw, self.price_mode, as_of_date=end_ts)
            sliced = normalized.loc[start_ts:end_ts]
            gaps = self._check_internal_gaps(sliced, start_ts, end_ts)
            diag = RefreshDiagnostics(
                symbol=symbol, cache_hit=False, cache_miss=True,
                refresh_start=start_date, refresh_end=end_date, overlap_sessions=0,
                previous_latest_session=None, new_latest_session=str(merged_raw.index.max().date()),
                rows_before=0, rows_after=len(merged_raw), rows_downloaded=len(raw),
                resolved_source=self._resolved_source_for(meta.source), internal_gap_sessions=gaps,
                range_complete=(len(gaps) == 0) if self.calendar is not None else None,
            )
            return sliced, diag

        previous_latest = str(cached_raw.index.max().date())
        rows_before = len(cached_raw)
        cached_start, cached_end = cached_raw.index.min(), cached_raw.index.max()
        needs_refresh, refresh_start_ts = False, start_ts

        if end_ts > cached_end:
            refresh_start_ts = max(start_ts, cached_end - pd.Timedelta(days=int(self.overlap_sessions * 1.5) + 3))
            needs_refresh = True
        if start_ts < cached_start:
            refresh_start_ts = min(refresh_start_ts, start_ts)
            needs_refresh = True

        if not needs_refresh:
            normalized = normalize_provider_frame(cached_raw, self.price_mode, as_of_date=end_ts)
            sliced = normalized.loc[start_ts:end_ts]
            gaps = self._check_internal_gaps(sliced, start_ts, end_ts)  # BLOCKER 11: checked even on a "hit"
            diag = RefreshDiagnostics(
                symbol=symbol, cache_hit=True, cache_miss=False,
                refresh_start=None, refresh_end=None, overlap_sessions=self.overlap_sessions,
                previous_latest_session=previous_latest, new_latest_session=previous_latest,
                rows_before=rows_before, rows_after=rows_before, rows_downloaded=0,
                resolved_source=_cache_meta.get("source") if _cache_meta else None,
                internal_gap_sessions=gaps, range_complete=(len(gaps) == 0) if self.calendar is not None else None,
            )
            return sliced, diag

        try:
            raw, meta = self.provider.get_daily_ohlcv(symbol, str(refresh_start_ts.date()), end_date)
        except DataUnavailableError:
            if start_ts >= cached_start:
                normalized = normalize_provider_frame(cached_raw, self.price_mode, as_of_date=end_ts)
                sliced = normalized.loc[start_ts:end_ts]
                gaps = self._check_internal_gaps(sliced, start_ts, end_ts)
                diag = RefreshDiagnostics(
                    symbol=symbol, cache_hit=True, cache_miss=False,
                    refresh_start=str(refresh_start_ts.date()), refresh_end=end_date,
                    overlap_sessions=self.overlap_sessions, previous_latest_session=previous_latest,
                    new_latest_session=previous_latest, rows_before=rows_before, rows_after=rows_before,
                    rows_downloaded=0, resolved_source=_cache_meta.get("source") if _cache_meta else None,
                    internal_gap_sessions=gaps, range_complete=(len(gaps) == 0) if self.calendar is not None else None,
                )
                return sliced, diag
            raise

        merged_raw = self.cache.write_merged(self.provider.name, symbol, raw, meta)
        normalized = normalize_provider_frame(merged_raw, self.price_mode, as_of_date=end_ts)
        sliced = normalized.loc[start_ts:end_ts]
        gaps = self._check_internal_gaps(sliced, start_ts, end_ts)
        diag = RefreshDiagnostics(
            symbol=symbol, cache_hit=True, cache_miss=False,
            refresh_start=str(refresh_start_ts.date()), refresh_end=end_date,
            overlap_sessions=self.overlap_sessions, previous_latest_session=previous_latest,
            new_latest_session=str(merged_raw.index.max().date()),
            rows_before=rows_before, rows_after=len(merged_raw), rows_downloaded=len(raw),
            resolved_source=self._resolved_source_for(meta.source), internal_gap_sessions=gaps,
            range_complete=(len(gaps) == 0) if self.calendar is not None else None,
        )
        return sliced, diag
