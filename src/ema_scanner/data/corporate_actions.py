"""Corporate actions + price-basis math (brief Phase-2 Section 1 — BLOCKER).

**Bug fixed here (see docs/NOTEBOOK_AUDIT.md and the Phase-2 review):** the
first version of this refactor computed a "split adjustment factor" as
`AdjClose / Close`. That is WRONG. Yahoo's `Adj Close` incorporates dividend
and capital-gain distributions as well as splits, so `AdjClose/Close` is a
**total-return** factor, not a pure split factor. Using it to rescale
Open/High/Low/Close for `SPLIT_ADJUSTED` silently contaminated every
downstream feature (EMA, ATR, cluster levels, swings, stops, forward returns)
with dividend effects that have nothing to do with share-count adjustment.

This module now computes the split-only adjustment factor directly from the
`Stock Splits` column yfinance returns with `actions=True` (a ratio, e.g. 2.0
for a 2-for-1 forward split, 0.5 for a 1-for-2 reverse split, 0.0 on days with
no split) -- dividends never enter this calculation.

## The algorithm (standard corporate-action back-adjustment, e.g. as used by
CRSP-style price databases and by yfinance's own internal adjustment code)

Working from the LATEST date backward to the EARLIEST:

    factor = 1.0
    for i from last index down to first index:
        adjustment_factor[i] = factor          # applies to this and all earlier
                                                 # rows not yet past a split
        if a split of ratio r occurred ON row i:
            factor = factor / r                 # earlier rows divide by r more

Price columns are multiplied by `adjustment_factor`; Volume is divided by it
(more new shares exist after a forward split, so historical share counts must
scale up to be comparable).

## Total-return series

Yahoo's `Adj Close` **is** a legitimate total-return-adjusted close (splits +
dividends/capital-gains reinvestment approximation) -- it was being *misused*
here, not wrong in itself. `total_return_series()` below simply exposes it
under its correct name, and this refactor does not attempt to build an
independent dividend-reinvestment model (that would be new, unverified
methodology -- brief Section 99: don't invent it silently).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    date: str
    kind: Literal["SPLIT", "BONUS", "RIGHTS", "MERGER", "SYMBOL_CHANGE", "DELISTING"]
    ratio: float | None = None
    new_symbol: str | None = None
    note: str | None = None


class CorporateActionsProvider:
    """Interface only -- no independent corporate-actions dataset is wired up
    (same as v1). Split handling for yfinance-sourced data does NOT depend on
    this class; it uses the provider's own `Stock Splits` column directly
    (see `compute_split_adjustment_factors` below), which is available today
    without a separate data source."""

    def get_actions(self, symbol: str, start_date: str, end_date: str) -> list[CorporateAction]:
        raise NotImplementedError("No independent corporate-actions data source is configured.")


def compute_split_adjustment_factors(stock_splits: pd.Series) -> pd.Series:
    """Pure split-only back-adjustment factor per date. `stock_splits` must be
    the raw per-date split ratio (0.0 / NaN where no split occurred that day).
    Never look at dividends here -- see module docstring."""
    s = stock_splits.fillna(0.0).to_numpy(dtype=float)
    n = len(s)
    factors = np.ones(n, dtype=float)
    factor = 1.0
    for i in range(n - 1, -1, -1):
        factors[i] = factor
        if s[i] and s[i] != 0.0:
            factor = factor / s[i]
    return pd.Series(factors, index=stock_splits.index, name="SplitAdjustmentFactor")


def apply_split_adjustment(df: pd.DataFrame, factors: pd.Series) -> pd.DataFrame:
    """Applies a split-only factor to OHLC (multiply) and Volume (divide).
    Does not touch any dividend/total-return column."""
    out = df.copy()
    for col in ("Open", "High", "Low", "Close"):
        if col in out.columns:
            out[col] = out[col] * factors
    if "Volume" in out.columns:
        safe_factors = factors.replace(0.0, np.nan)
        out["Volume"] = (out["Volume"] / safe_factors).fillna(out["Volume"])
    return out


def total_return_series(adj_close: pd.Series) -> pd.Series:
    """Exposes yfinance's `Adj Close` under its correct name: a total-return
    (splits + dividends) adjusted close. This is a DISTINCT series from
    SPLIT_ADJUSTED_OHLCV's Close and must never be substituted for it in
    EMA/ATR/swing/stop calculations (brief Phase-2 Section 1)."""
    return adj_close.rename("TotalReturnClose")


def point_in_time_split_adjustment(raw_ohlcv: pd.DataFrame, stock_splits: pd.Series, as_of_date) -> pd.DataFrame:
    """Phase-3 BLOCKER 1 fix: masks out any split event whose date is AFTER
    `as_of_date` before computing the back-adjustment factor, so
    `signal_features(D)` computed with `as_of_date=D` is invariant to any
    corporate-action record that hadn't happened yet as of D.

    Without this, a symbol's back-adjustment factor is a function of the
    LATEST split present anywhere in the raw series -- so if the underlying
    raw dataset later grows to include a split that occurs AFTER D (e.g. the
    cache is refreshed for a more recent live scan, or a walk-forward fold
    evaluates a later out-of-sample window from the same raw frame), the
    factor applied to ALL rows up to and including D would retroactively
    change, silently altering `signal_features(D)` after the fact -- a form
    of look-ahead leakage through the corporate-action adjustment step
    itself, distinct from (and not addressed by) the earlier AdjClose/Close
    bug fix. See tests/lookahead/test_point_in_time_corporate_actions.py.
    """
    as_of = pd.Timestamp(as_of_date)
    masked_splits = stock_splits.copy()
    masked_splits[masked_splits.index > as_of] = 0.0
    factors = compute_split_adjustment_factors(masked_splits)
    return apply_split_adjustment(raw_ohlcv, factors)
