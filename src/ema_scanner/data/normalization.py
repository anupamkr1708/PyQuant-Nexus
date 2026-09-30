"""Provider-agnostic normalization + explicit price-basis separation
(brief Phase-2 Section 1 -- BLOCKER; docs/NOTEBOOK_AUDIT.md; Phase-3 BLOCKER 1).

Four DISTINCT price bases are now modeled explicitly, matching the Phase-2
review's required architecture:

    RAW_OHLCV              -- provider's data, untouched.
    SPLIT_ADJUSTED_OHLCV    -- RAW rescaled by a PURE split-only factor
                               (data/corporate_actions.py), NEVER by
                               AdjClose/Close (that mixes in dividends -- the
                               bug this rewrite fixes).
    TOTAL_RETURN_SERIES     -- yfinance's own `Adj Close`, exposed under its
                               correct name. A single Series, not an OHLCV
                               frame (Yahoo does not publish total-return
                               Open/High/Low) -- used only where an explicit
                               total-return comparison is wanted (e.g. a
                               dividend-aware performance sanity check), NEVER
                               fed into EMA/ATR/swing/stop calculations.
    EXECUTION_OHLCV         -- the basis actually used for execution-price
                               resolution (execution/execution_models.py).
                               By ENGINEERING_DECISION this equals
                               SPLIT_ADJUSTED_OHLCV, not RAW: mixing a raw
                               (unadjusted) execution price with split-
                               adjusted signal/stop levels would create
                               spurious quantity/price mismatches across a
                               split boundary. Documented here rather than
                               silently assumed.

`price_mode` in config selects which OHLCV basis (RAW or SPLIT_ADJUSTED) feeds
the strategy AND execution layers -- one consistent basis throughout, per
brief Section 21.

**Phase-3 BLOCKER 1:** `as_of_date` now threads through
`normalize_provider_frame` -> `split_adjusted_ohlcv` ->
`point_in_time_split_adjustment`, so the adjustment factor used never
reflects a corporate action dated after the caller's own decision date. See
data/corporate_actions.py::point_in_time_split_adjustment for the mechanism
and data/repository.py for where this is wired to the actual analysis date.
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.data.corporate_actions import (
    apply_split_adjustment,
    compute_split_adjustment_factors,
    point_in_time_split_adjustment,
    total_return_series,
)

REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]


def raw_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """RAW_OHLCV: provider data, untouched (beyond selecting the standard columns)."""
    missing = set(REQUIRED_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"raw_ohlcv: missing required columns {sorted(missing)}")
    return df[REQUIRED_COLS].copy()


def split_adjusted_ohlcv(df: pd.DataFrame, as_of_date=None) -> pd.DataFrame:
    """SPLIT_ADJUSTED_OHLCV: RAW rescaled by a PURE split-only factor derived
    from the `Stock Splits` column. If that column isn't present (e.g. a
    provider that doesn't supply corporate-action data), returns RAW
    unchanged with no adjustment -- it does NOT fall back to AdjClose/Close
    (that would reintroduce the exact bug this module exists to fix).

    Phase-3 BLOCKER 1: pass `as_of_date` (the analysis/decision date the
    resulting series will be used for) to mask out any split event AFTER
    that date before computing the adjustment factor -- otherwise the
    factor is a function of the LATEST split anywhere in `df`, which can
    retroactively change historical values as the raw dataset grows (see
    data/corporate_actions.py::point_in_time_split_adjustment).
    `as_of_date=None` is for ad-hoc calls with no specific decision date in
    mind; production code paths (data/repository.py) always pass it.
    """
    base = raw_ohlcv(df)
    if "Stock Splits" not in df.columns:
        return base
    if as_of_date is not None:
        return point_in_time_split_adjustment(base, df["Stock Splits"], as_of_date)
    factors = compute_split_adjustment_factors(df["Stock Splits"])
    return apply_split_adjustment(base, factors)


def total_return_close(df: pd.DataFrame) -> pd.Series | None:
    """TOTAL_RETURN_SERIES: yfinance's `AdjClose`/`Adj Close`, exposed under
    its correct name. Returns None if the provider didn't supply it (e.g. the
    NSE bhavcopy provider, which has no dividend-adjusted series at all)."""
    col = "AdjClose" if "AdjClose" in df.columns else ("Adj Close" if "Adj Close" in df.columns else None)
    if col is None:
        return None
    return total_return_series(df[col])


def normalize_provider_frame(raw: pd.DataFrame, price_mode: str = "SPLIT_ADJUSTED", as_of_date=None) -> pd.DataFrame:
    """Selects the OHLCV basis that feeds the strategy/execution layers.

    RAW              -> raw_ohlcv(raw)
    SPLIT_ADJUSTED   -> split_adjusted_ohlcv(raw, as_of_date)   [pure split factor, point-in-time -- see module docstring]
    TOTAL_RETURN_ADJUSTED -> NOT IMPLEMENTED as an OHLCV basis (Yahoo publishes
        no total-return Open/High/Low, only a Close-level series). Use
        total_return_close(raw) directly for a Close-only total-return
        comparison instead; this function raises rather than silently
        approximating an OHLCV frame that doesn't really exist.

    `as_of_date`: the decision/analysis date this normalized series will be
    used for (Phase-3 BLOCKER 1). Strongly recommended for any production
    code path; omit only for quick ad-hoc inspection where point-in-time
    correctness doesn't matter.
    """
    if price_mode == "RAW":
        return raw_ohlcv(raw)
    if price_mode == "SPLIT_ADJUSTED":
        return split_adjusted_ohlcv(raw, as_of_date=as_of_date)
    if price_mode == "TOTAL_RETURN_ADJUSTED":
        raise NotImplementedError(
            "TOTAL_RETURN_ADJUSTED is not an OHLCV basis (Yahoo publishes no "
            "total-return Open/High/Low, only a Close-level series). Use "
            "data.normalization.total_return_close(raw_df) for a Close-only "
            "total-return comparison, and RAW or SPLIT_ADJUSTED for the "
            "OHLCV basis that feeds features/strategy/execution."
        )
    raise ValueError(f"Unknown price_mode: {price_mode!r}")
