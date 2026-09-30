"""Market regime diagnostic (notebook Cell 30; audit row 25; Phase-3 BLOCKER 7).

OPTIONAL FILTER / diagnostic-first (brief Section 33): regime is reported for
segmentation, never auto-applied as a filter unless explicitly enabled downstream.
Benchmark is configurable (NIFTY50 default, matching the notebook's `^NSEI` choice,
or NIFTY200 / a custom index) -- the notebook's own default is NOT silently changed.

**Bug fixed (Phase-3 BLOCKER 7):** `strategy.regime.benchmark` and
`index_ema_*` existed in config but important CLI code paths still called
`compute_market_regime(index_df)` with a HARD-CODED `^NSEI` fetch and the
function's own default EMA periods, silently ignoring both config fields.
`resolve_benchmark(cfg)` is now the ONE place a benchmark symbol is decided,
and CLI code calls it instead of hard-coding `^NSEI`; `compute_market_regime`
callers are all updated to pass `cfg.strategy.regime.index_ema_*` explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ema_scanner.config import RegimeConfig
from ema_scanner.features.ema import compute_ema


class BenchmarkResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedBenchmark:
    symbol: str
    label: str
    source: str  # e.g. "yfinance" -- which provider ticker namespace this symbol is meant for


def resolve_benchmark(cfg: RegimeConfig) -> ResolvedBenchmark:
    """The ONE place a benchmark ticker symbol is decided from config.

    NIFTY50 -> "^NSEI": verified (this is the notebook's own original
    choice, and matches the ticker this refactor's yfinance provider has
    already been exercised against via the XNSE calendar cross-check --
    see docs/DATA_SOURCES.md).

    NIFTY200 -> **deliberately NOT resolved to a guessed ticker.** A web
    search while building this fix did not turn up a source confirming a
    working yfinance/Yahoo Finance ticker for a NIFTY 200 total-index
    series (several third-party sites reference "CNX200" branding, but none
    confirmed a working Yahoo Finance quote symbol) -- per brief Section 100
    ("do not invent URLs or endpoints"), this raises a clear, actionable
    error rather than silently trying an unverified symbol. Use CUSTOM with
    a symbol you've personally confirmed instead.

    CUSTOM -> `cfg.custom_benchmark_symbol`, required.
    """
    if cfg.benchmark == "NIFTY50":
        return ResolvedBenchmark(symbol="^NSEI", label="NIFTY 50", source="yfinance")
    if cfg.benchmark == "NIFTY200":
        raise BenchmarkResolutionError(
            "strategy.regime.benchmark=NIFTY200 has no verified Yahoo Finance ticker "
            "wired up in this build (see docs/DATA_SOURCES.md) -- refusing to guess one. "
            "Confirm the correct symbol yourself and set "
            "strategy.regime.benchmark=CUSTOM with strategy.regime.custom_benchmark_symbol."
        )
    if cfg.benchmark == "CUSTOM":
        if not cfg.custom_benchmark_symbol:
            raise BenchmarkResolutionError(
                "strategy.regime.benchmark=CUSTOM requires strategy.regime.custom_benchmark_symbol to be set."
            )
        return ResolvedBenchmark(symbol=cfg.custom_benchmark_symbol, label=f"Custom ({cfg.custom_benchmark_symbol})", source="yfinance")
    raise BenchmarkResolutionError(f"Unknown benchmark: {cfg.benchmark!r}")


def compute_market_regime(
    index_df: pd.DataFrame, close_col: str = "Close",
    ema_fast: int = 20, ema_medium: int = 50, ema_structural: int = 89, ema_long: int = 200,
) -> pd.DataFrame:
    out = index_df.copy()
    out["Index_EMA20"] = compute_ema(out[close_col], ema_fast)
    out["Index_EMA50"] = compute_ema(out[close_col], ema_medium)
    out["Index_EMA89"] = compute_ema(out[close_col], ema_structural)
    out["Index_EMA200"] = compute_ema(out[close_col], ema_long)
    price = out[close_col]
    bull = (price > out["Index_EMA50"]) & (out["Index_EMA50"] > out["Index_EMA200"])
    bear = (price < out["Index_EMA50"]) & (out["Index_EMA50"] < out["Index_EMA200"])
    regime = pd.Series("NEUTRAL", index=out.index)
    regime[bull], regime[bear] = "BULL", "BEAR"
    regime[out["Index_EMA200"].isna()] = None
    out["Market_Regime"] = regime
    return out[["Market_Regime", "Index_EMA20", "Index_EMA50", "Index_EMA89", "Index_EMA200"]]


def attach_market_regime_asof(stock_df: pd.DataFrame, regime_df: pd.DataFrame) -> pd.Series:
    return regime_df["Market_Regime"].reindex(stock_df.index, method="ffill")
