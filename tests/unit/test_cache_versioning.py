"""BLOCKER 12 (Phase-3): cache versioning must invalidate on schema change."""
import json
import tempfile
from pathlib import Path

import pandas as pd

from ema_scanner.data.base import ProviderMetadata
from ema_scanner.data.cache import DataCache


def test_cache_with_stale_schema_version_is_treated_as_a_miss():
    with tempfile.TemporaryDirectory() as tmp:
        cache = DataCache(tmp)
        dates = pd.bdate_range("2024-01-01", periods=5)
        df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=dates)
        meta = ProviderMetadata("x", "x", "now", "2024-01-01", "2024-01-05", "v1")
        cache.write_merged("prov", "AAA", df, meta)

        # confirm a normal read succeeds first
        cached, _ = cache.read("prov", "AAA")
        assert cached is not None

        # simulate an old/incompatible schema_version written by a prior code version
        meta_path = Path(tmp) / "prov__AAA__1d__raw.meta.json"
        stored = json.loads(meta_path.read_text())
        stored["schema_version"] = "raw_v0_ancient"
        meta_path.write_text(json.dumps(stored))

        cached_after, _meta_after = cache.read("prov", "AAA")
        assert cached_after is None, "a stale schema_version must be treated as a cache MISS, never silently reused"


def test_missing_metadata_file_is_also_treated_as_a_miss():
    with tempfile.TemporaryDirectory() as tmp:
        cache = DataCache(tmp)
        dates = pd.bdate_range("2024-01-01", periods=5)
        df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=dates)
        meta = ProviderMetadata("x", "x", "now", "2024-01-01", "2024-01-05", "v1")
        cache.write_merged("prov", "BBB", df, meta)
        meta_path = Path(tmp) / "prov__BBB__1d__raw.meta.json"
        meta_path.unlink()
        cached, _ = cache.read("prov", "BBB")
        assert cached is None
