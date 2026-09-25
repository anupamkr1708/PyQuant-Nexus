"""Synthetic fixtures for pipeline-plumbing tests ONLY (brief Section 16: never
used for production scan / research / backtest / signal generation)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_synthetic_ohlcv(n: int = 500, seed: int = 42, start: str = "2018-01-01", drift: float = 0.03, vol: float = 1.2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    close = 100 + np.cumsum(rng.normal(drift, vol, n))
    openp = close + rng.normal(0, 0.3, n)
    high = np.maximum(close, openp) + rng.uniform(0.1, 1.0, n)
    low = np.minimum(close, openp) - rng.uniform(0.1, 1.0, n)
    volume = rng.integers(50_000, 800_000, n)
    return pd.DataFrame({"Open": openp, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


def make_step_series(n: int = 100, start: str = "2020-01-01") -> pd.Series:
    dates = pd.bdate_range(start, periods=n)
    values = np.concatenate([np.full(n // 2, 100.0), np.full(n - n // 2, 120.0)])
    return pd.Series(values, index=dates)
