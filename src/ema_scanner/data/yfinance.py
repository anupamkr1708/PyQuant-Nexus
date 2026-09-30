"""Yahoo Finance SECONDARY provider (brief Sections 13, 15).

Pinned to yfinance==1.7.0 (verified installable from PyPI on 2026-09-23 — see
DATA_SOURCES.md). Every parameter yfinance's `download()` would otherwise
default is set explicitly here rather than inherited:

- `end` is EXCLUSIVE in yfinance (confirmed directly from the installed 1.7.0
  docstring: "for end='2023-01-01', the last data point will be on
  '2022-12-31'"). This provider adds one calendar day to the requested
  `end_date` before calling the API so the caller's own inclusive `end_date`
  semantics are honored. See tests/unit/test_yfinance_provider.py for a test of
  this using an injected fake downloader (no live network call).
- `auto_adjust=False`: we fetch RAW OHLC plus a separate `Adj Close` column and
  let data/normalization.py decide which price series to expose for the
  configured `price_mode`, rather than letting yfinance silently adjust
  everything (yfinance 1.7.0's own default for `auto_adjust` is `True`, which
  this provider deliberately overrides — brief Section 21: don't let a
  provider default decide the price mode).
- `actions=True`: also pulls dividends/splits, needed for
  data/corporate_actions.py.
- `repair=False` (Phase-3 BLOCKER 24): yfinance's `repair=True` silently
  applies vendor-side heuristic corrections to detected bad ticks (e.g.
  100x/currency errors, some split/dividend mismatches) without separately
  exposing WHAT was changed. Per the Phase-3 review's explicit preference
  ("prefer repair=False unless repaired observations are separately
  captured and auditable"), this provider defaults to `repair=False` --
  any bad ticks in the raw feed surface as-is and are caught by
  `data/quality.py`'s explicit checks (non-finite values, High<Low, etc.)
  instead of being invisibly pre-cleaned by the vendor. This choice is
  recorded in `ProviderMetadata` and should be surfaced in the run manifest
  so it's never a hidden research-preprocessing step.
- `threads=False` (predictable single-symbol calls),
  `interval="1d"`, `timeout` explicit.

NOTE: this provider's `get_daily_ohlcv` has NOT been exercised against the live
Yahoo Finance API in this environment — the sandboxed network here does not
allow reaching finance.yahoo.com (see RESEARCH_LIMITATIONS.md). The code is
real and should work unmodified with normal network access; verify with
`ema-scanner validate-data` before trusting it for a live scan.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ema_scanner.data.base import DataProvider, DataUnavailableError, ProviderMetadata

YFINANCE_PINNED_VERSION = "1.7.0"


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def __init__(self, symbol_suffix: str = ".NS"):
        self.symbol_suffix = symbol_suffix  # NSE tickers on Yahoo are e.g. "RELIANCE.NS"

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, ProviderMetadata]:
        try:
            import yfinance as yf
        except ImportError as e:
            raise DataUnavailableError(f"yfinance not installed: {e}") from e

        ticker = symbol if symbol.endswith(self.symbol_suffix) else f"{symbol}{self.symbol_suffix}"
        exclusive_end = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).date().isoformat()

        try:
            raw = yf.download(
                tickers=ticker, start=start_date, end=exclusive_end, interval="1d",
                auto_adjust=False, actions=True, repair=False, threads=False,
                progress=False, timeout=30, multi_level_index=False,
            )
        except Exception as e:  # yfinance raises a variety of exception types
            raise DataUnavailableError(f"yfinance download failed for {ticker}: {e}") from e

        if raw is None or raw.empty:
            raise DataUnavailableError(f"yfinance returned no data for {ticker} [{start_date}, {end_date}]")

        df = raw.rename(columns={"Adj Close": "AdjClose"})
        keep = [c for c in ["Open", "High", "Low", "Close", "AdjClose", "Volume", "Dividends", "Stock Splits"] if c in df.columns]
        df = df[keep].copy()
        df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
        df.index.name = "Date"
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]

        requested_end = pd.Timestamp(end_date).normalize()
        if df.index.max() < requested_end and (requested_end - df.index.max()).days <= 5:
            pass  # normal: requested end may itself be a non-trading day; not an error

        meta = ProviderMetadata(
            source="yfinance", endpoint=f"yf.download({ticker})",
            retrieval_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            trade_date_coverage_start=str(df.index.min().date()),
            trade_date_coverage_end=str(df.index.max().date()),
            schema_version="yfinance_v1", parser_version=YFINANCE_PINNED_VERSION,
            vendor_repair_enabled=False,
        )
        return df, meta
