"""EMA engine (notebook Cell 14/16; docs/NOTEBOOK_AUDIT.md rows 1-2, 16).

MATHEMATICAL DEFINITION, preserved exactly:

    EMA_t = (Price_t - EMA_{t-1}) * multiplier + EMA_{t-1}
    multiplier = 2 / (period + 1)

seed_method='sma' (default): EMA is NaN for the first `period-1` bars; EMA at bar
`period-1` is seeded as the simple mean of the first `period` observations
(textbook / TA-Lib convention), then the recursion above takes over.

seed_method='first_obs': EMA_0 = Price_0, recursion from bar 0 (documented
alternative, NOT the default — never silently switched).

Deliberately implemented as an explicit Python loop (not `.ewm()`), matching the
notebook, so `adjust`/`min_periods`/seeding are all visible rather than inherited
from a library default (brief Section 3). See tests/unit/test_ema.py for the
cross-check against a trusted pandas `.ewm(adjust=False)` reference.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ema_scanner.config import EMAConfig

EMA_ROLE_NAMES = ("EMA10", "EMA20", "EMA89", "EMA200")  # role names, NOT literal periods
_ROLE_TO_FIELD = {"EMA10": "fast", "EMA20": "medium", "EMA89": "structural", "EMA200": "long"}


def compute_ema(series: pd.Series, period: int, seed_method: str = "sma") -> pd.Series:
    if period <= 0:
        raise ValueError(f"EMA period must be positive, got {period}")
    values = series.to_numpy(dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    multiplier = 2.0 / (period + 1.0)

    if seed_method == "sma":
        if n < period:
            return pd.Series(out, index=series.index, name=series.name)
        seed_idx = period - 1
        out[seed_idx] = np.nanmean(values[:period])
        for t in range(seed_idx + 1, n):
            out[t] = (values[t] - out[t - 1]) * multiplier + out[t - 1]
    elif seed_method == "first_obs":
        if n == 0:
            return pd.Series(out, index=series.index, name=series.name)
        out[0] = values[0]
        for t in range(1, n):
            out[t] = (values[t] - out[t - 1]) * multiplier + out[t - 1]
    else:
        raise ValueError(f"Unknown EMA seed_method: {seed_method!r}")
    return pd.Series(out, index=series.index, name=series.name)


def compute_all_emas(
    df: pd.DataFrame,
    price_col: str = "Close",
    suffix: str = "",
    ema_cfg: EMAConfig | None = None,
) -> pd.DataFrame:
    """Attaches role-named EMA10/20/89/200 (+ optional suffix, e.g. '_W' for
    weekly) columns. `ema_cfg` lets sensitivity analysis perturb periods without
    mutating a shared global config object (brief Section 58)."""
    if ema_cfg is None:
        ema_cfg = EMAConfig()
    out = df.copy()
    periods = {
        "EMA10": ema_cfg.fast,
        "EMA20": ema_cfg.medium,
        "EMA89": ema_cfg.structural,
        "EMA200": ema_cfg.long,
    }
    for role, period in periods.items():
        out[f"{role}{suffix}"] = compute_ema(out[price_col], period, seed_method=ema_cfg.seed_method)
    return out


def reference_ema_pandas_adjust_false(series: pd.Series, period: int) -> pd.Series:
    """Trusted reference implementation used ONLY in tests: pandas' `.ewm(adjust=False)`,
    seeded identically to `compute_ema`'s 'sma' seeding, so this checks the RECURSIVE
    STEP, not the seed choice itself (which has no single "correct" answer — see
    STRATEGY_SPEC.md)."""
    values = series.to_numpy(dtype=float)
    n, seed_idx = len(values), period - 1
    if n <= seed_idx:
        return pd.Series(np.full(n, np.nan), index=series.index)
    seed_val = np.nanmean(values[:period])
    tail = pd.Series(values[seed_idx:])
    tail.iloc[0] = seed_val
    ema_tail = tail.ewm(span=period, adjust=False).mean()
    out = np.full(n, np.nan)
    out[seed_idx:] = ema_tail.to_numpy()
    return pd.Series(out, index=series.index)
