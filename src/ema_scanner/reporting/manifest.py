"""Run manifest writer (brief Section 61)."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ema_scanner.models import RunManifest
from ema_scanner.utils.serialization import to_jsonable


def build_run_manifest(**kwargs) -> RunManifest:
    kwargs.setdefault("run_id", str(uuid.uuid4()))
    kwargs.setdefault("run_timestamp_utc", datetime.now(timezone.utc).isoformat())
    kwargs.setdefault("python_version", sys.version)
    return RunManifest(**kwargs)


def package_versions() -> dict:
    import importlib.metadata as md
    names = ["pandas", "numpy", "pandas_market_calendars", "yfinance", "pydantic", "pyarrow"]
    out = {}
    for n in names:
        try:
            out[n] = md.version(n)
        except Exception:  # noqa: BLE001 - one package's version lookup failing must not block writing the run manifest
            out[n] = "unknown"
    return out


def write_manifest(manifest: RunManifest, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(to_jsonable(manifest), indent=2, default=str))
