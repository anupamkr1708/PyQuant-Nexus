"""Industry-grade parquet cache (brief Section 17).

Keyed by (provider, symbol, frequency, adjustment_mode); merges incrementally,
deduplicates, sorts, and writes atomically (write to a temp file, then
os.replace) so a crash mid-write never corrupts the cache. Stores metadata
alongside each cached series (brief Section 17: retrieved_at, source, coverage,
row_count, hash).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ema_scanner.data.base import ProviderMetadata
from ema_scanner.utils.hashing import sha256_dataframe


class DataCache:
    def __init__(self, root: str | Path = "data/cache"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, provider: str, symbol: str, frequency: str, adjustment_mode: str) -> str:
        safe_symbol = symbol.replace("/", "_")
        return f"{provider}__{safe_symbol}__{frequency}__{adjustment_mode}"

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.root / f"{key}.parquet", self.root / f"{key}.meta.json"

    def read(self, provider: str, symbol: str, frequency: str = "1d", adjustment_mode: str = "SPLIT_ADJUSTED") -> tuple[pd.DataFrame | None, dict | None]:
        data_path, meta_path = self._paths(self._key(provider, symbol, frequency, adjustment_mode))
        if not data_path.exists():
            return None, None
        df = pd.read_parquet(data_path)
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
        return df, meta

    def write_merged(
        self, provider: str, symbol: str, new_df: pd.DataFrame, provider_metadata: ProviderMetadata,
        frequency: str = "1d", adjustment_mode: str = "SPLIT_ADJUSTED",
    ) -> pd.DataFrame:
        """Merges `new_df` into any existing cached data for this key: incremental
        merge, dedupe by index (new data wins on conflict, since vendor
        corrections can revise recent bars — brief Section 18), sort, then
        atomic write."""
        key = self._key(provider, symbol, frequency, adjustment_mode)
        data_path, meta_path = self._paths(key)
        existing, _ = self.read(provider, symbol, frequency, adjustment_mode)
        if existing is not None and not existing.empty:
            combined = pd.concat([existing[~existing.index.isin(new_df.index)], new_df])
        else:
            combined = new_df
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()

        fd, tmp_path = tempfile.mkstemp(suffix=".parquet", dir=self.root)
        os.close(fd)
        combined.to_parquet(tmp_path)
        os.replace(tmp_path, data_path)

        meta = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": provider_metadata.source,
            "endpoint": provider_metadata.endpoint,
            "coverage_start": str(combined.index.min().date()),
            "coverage_end": str(combined.index.max().date()),
            "row_count": len(combined),
            "hash": sha256_dataframe(combined),
            "schema_version": provider_metadata.schema_version,
            "parser_version": provider_metadata.parser_version,
        }
        meta_path.write_text(json.dumps(meta, indent=2))
        return combined
