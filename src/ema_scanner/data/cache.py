"""RAW-data-preserving parquet cache (brief Section 17; Phase-3 BLOCKERS 2, 12).

**Bug fixed (BLOCKER 2):** v1 cached the ALREADY-NORMALIZED (adjusted) OHLCV,
which discarded `Dividends`/`Stock Splits`/`AdjClose` -- making the durable
cache unable to support point-in-time re-normalization (BLOCKER 1) at all,
since the corporate-action data needed for that was simply gone after the
first write. This cache now stores RAW provider output (every column the
provider returned, including action fields) as the one durable source of
truth. Normalization into a research OHLCV basis happens FRESH at read time
in `data/repository.py`, using the caller's own `as_of_date` -- so it is
always point-in-time correct even though the raw cache only grows over time
and is never itself re-adjusted.

**Bug fixed (BLOCKER 12):** cache entries now carry a `schema_version`. If a
future code change alters what "raw" means for a provider (e.g. a different
yfinance call shape), bumping `RAW_CACHE_SCHEMA_VERSION` makes any
previously-cached data for the OLD schema treated as a cache MISS (not
silently reused) on next read, forcing a clean full re-fetch rather than
mixing schemas. Because normalization/corporate-action logic runs at READ
TIME on raw data rather than being cached itself, changes to THOSE algorithms
never need explicit cache invalidation at all -- the next read simply
produces different (correct, current) output from the same raw cache.
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

RAW_CACHE_SCHEMA_VERSION = "raw_v1"


class DataCache:
    def __init__(self, root: str | Path = "data/cache"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, provider: str, symbol: str, frequency: str) -> str:
        safe_symbol = symbol.replace("/", "_")
        return f"{provider}__{safe_symbol}__{frequency}__raw"

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.root / f"{key}.parquet", self.root / f"{key}.meta.json"

    def read(self, provider: str, symbol: str, frequency: str = "1d") -> tuple[pd.DataFrame | None, dict | None]:
        data_path, meta_path = self._paths(self._key(provider, symbol, frequency))
        if not data_path.exists():
            return None, None
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
        # BLOCKER 12: a schema-version mismatch is treated as a cache MISS,
        # never a silent reuse of incompatible historical cache artifacts.
        if meta is None or meta.get("schema_version") != RAW_CACHE_SCHEMA_VERSION:
            return None, None
        df = pd.read_parquet(data_path)
        return df, meta

    def write_merged(
        self, provider: str, symbol: str, new_df: pd.DataFrame, provider_metadata: ProviderMetadata,
        frequency: str = "1d",
    ) -> pd.DataFrame:
        """Merges `new_df` (RAW provider columns, untouched) into any existing
        cached data for this key: incremental merge, dedupe by index (new
        data wins on conflict, since vendor corrections can revise recent
        bars -- brief Section 18), sort, then atomic write."""
        key = self._key(provider, symbol, frequency)
        data_path, meta_path = self._paths(key)
        existing, _existing_meta = self.read(provider, symbol, frequency)
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
            "schema_version": RAW_CACHE_SCHEMA_VERSION,
            "provider_schema_version": provider_metadata.schema_version,
            "provider_version": provider_metadata.parser_version,
            "vendor_repair_enabled": provider_metadata.vendor_repair_enabled,
            "columns": list(combined.columns),
        }
        meta_path.write_text(json.dumps(meta, indent=2))
        return combined
