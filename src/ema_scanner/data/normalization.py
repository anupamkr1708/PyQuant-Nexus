"""Provider-agnostic normalization + explicit price-basis separation
(brief Phase-2 Section 1 -- BLOCKER; docs/NOTEBOOK_AUDIT.md).

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
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.data.corporate_actions import (
    apply_split_adjustment,
    compute_split_adjustment_factors,
    total_return_series,
)

REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]


def raw_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """RAW_OHLCV: provider data, untouched (beyond selecting the standard columns)."""
    missing = set(REQUIRED_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"raw_ohlcv: missing required columns {sorted(missing)}")
    return df[REQUIRED_COLS].copy()


def split_adjusted_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """SPLIT_ADJUSTED_OHLCV: RAW rescaled by a PURE split-only factor derived
    from the `Stock Splits` column. If that column isn't present (e.g. a
    provider that doesn't supply corporate-action data), returns RAW
    unchanged with no adjustment -- it does NOT fall back to AdjClose/Close
    (that would reintroduce the exact bug this module exists to fix)."""
    base = raw_ohlcv(df)
    if "Stock Splits" not in df.columns:
        return base
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


def normalize_provider_frame(raw: pd.DataFrame, price_mode: str = "SPLIT_ADJUSTED") -> pd.DataFrame:
    """Selects the OHLCV basis that feeds the strategy/execution layers.

    RAW              -> raw_ohlcv(raw)
    SPLIT_ADJUSTED   -> split_adjusted_ohlcv(raw)   [pure split factor -- see module docstring]
    TOTAL_RETURN_ADJUSTED -> NOT IMPLEMENTED as an OHLCV basis (Yahoo publishes
        no total-return Open/High/Low, only a Close-level series). Use
        total_return_close(raw) directly for a Close-only total-return
        comparison instead; this function raises rather than silently
        approximating an OHLCV frame that doesn't really exist.
    """
    if price_mode == "RAW":
        return raw_ohlcv(raw)
    if price_mode == "SPLIT_ADJUSTED":
        return split_adjusted_ohlcv(raw)
    if price_mode == "TOTAL_RETURN_ADJUSTED":
        raise NotImplementedError(
            "TOTAL_RETURN_ADJUSTED is not an OHLCV basis (Yahoo publishes no "
            "total-return Open/High/Low, only a Close-level series). Use "
            "data.normalization.total_return_close(raw_df) for a Close-only "
            "total-return comparison, and RAW or SPLIT_ADJUSTED for the "
            "OHLCV basis that feeds features/strategy/execution."
        )
    raise ValueError(f"Unknown price_mode: {price_mode!r}")
