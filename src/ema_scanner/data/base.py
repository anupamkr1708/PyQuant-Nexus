"""Data provider abstraction (brief Section 13). Strategy code (features/,
strategy/) knows NOTHING about yfinance or NSE internals — it only ever sees a
normalized OHLCV DataFrame from `get_daily_ohlcv`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


class DataUnavailableError(RuntimeError):
    """Raised instead of ever returning synthetic data in production (brief
    Section 16: 'FAIL LOUDLY... Return DATA_UNAVAILABLE and a detailed error.')."""


@dataclass
class ProviderMetadata:
    source: str
    endpoint: str | None
    retrieval_timestamp_utc: str
    trade_date_coverage_start: str | None
    trade_date_coverage_end: str | None
    schema_version: str
    raw_file_hash: str | None = None
    parser_version: str = "1"


class DataProvider(ABC):
    name: str

    @abstractmethod
    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, ProviderMetadata]:
        """Returns a normalized OHLCV frame (columns Open/High/Low/Close/Volume,
        DatetimeIndex named 'Date', ascending, no duplicate dates) plus provenance
        metadata. Must raise DataUnavailableError, never return empty/synthetic
        data silently, on failure."""
        raise NotImplementedError


class CompositeDataProvider(DataProvider):
    """Tries providers in order; falls through to the next on
    DataUnavailableError. Never falls through to synthetic data (brief Section
    16) — if every real provider fails, it raises DataUnavailableError itself."""

    name = "composite"

    def __init__(self, providers: list[DataProvider]):
        if not providers:
            raise ValueError("CompositeDataProvider requires at least one provider")
        self.providers = providers

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str):
        errors = []
        for p in self.providers:
            try:
                return p.get_daily_ohlcv(symbol, start_date, end_date)
            except DataUnavailableError as e:
                errors.append(f"{p.name}: {e}")
        raise DataUnavailableError(
            f"All providers failed for {symbol} [{start_date}, {end_date}]: " + " | ".join(errors)
        )
