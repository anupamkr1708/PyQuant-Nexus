"""JSON-safe serialization helpers for manifests/logs."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass


def to_jsonable(obj):
    if is_dataclass(obj):
        obj = asdict(obj)
    return json.loads(json.dumps(obj, default=str))
