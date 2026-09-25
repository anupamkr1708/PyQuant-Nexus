"""Content hashing for cache/provenance metadata (brief Sections 14, 17)."""
from __future__ import annotations

import hashlib


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_dataframe(df) -> str:
    import pandas as pd  # local import to keep module import-light
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()
