"""Performance statistics (notebook Cell 38; audit row 30).

EMPIRICALLY TESTED RESULT (methodology): descriptive statistics of a historical
sample, never a guarantee of future performance (brief Section 102). Includes a
block-bootstrap confidence interval, which the notebook does NOT have (brief
Section 54) — new code, kept simple and clustered by ticker to acknowledge
overlapping/correlated signals rather than assuming iid observations (brief
Section 52-54).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def performance_stats(returns_pct: pd.Series) -> dict:
    r = returns_pct.dropna()
    if len(r) == 0:
        return {"n_trades": 0}
    wins, losses = r[r > 0], r[r <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else np.nan
    equity_curve = (1 + r / 100.0).cumprod()
    drawdown = (equity_curve / equity_curve.cummax() - 1.0) * 100.0
    return {
        "n_trades": len(r),
        "win_rate_pct": float(len(wins) / len(r) * 100.0),
        "avg_return_pct": float(r.mean()),
        "median_return_pct": float(r.median()),
        "std_return_pct": float(r.std()),
        "profit_factor": float(profit_factor) if pd.notna(profit_factor) else np.nan,
        "expectancy_pct": float(r.mean()),
        "avg_win_pct": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss_pct": float(losses.mean()) if len(losses) else np.nan,
        "best_trade_pct": float(r.max()),
        "worst_trade_pct": float(r.min()),
        "max_drawdown_pct": float(drawdown.min()),
        "skew": float(r.skew()) if len(r) > 2 else np.nan,
    }


def performance_stats_by_group(event_df: pd.DataFrame, return_col: str, group_col: str) -> pd.DataFrame:
    if group_col not in event_df.columns:
        return pd.DataFrame()
    rows = []
    for g, sub in event_df.groupby(group_col, dropna=True):
        stats = performance_stats(sub[return_col])
        stats[group_col] = g
        rows.append(stats)
    return pd.DataFrame(rows)


def block_bootstrap_ci(
    event_df: pd.DataFrame, return_col: str, cluster_col: str = "Ticker",
    n_boot: int = 2000, ci: float = 0.95, seed: int = 42,
) -> dict:
    """Cluster (block) bootstrap CI for the mean of `return_col`, resampling whole
    tickers with replacement rather than individual rows, since signals from the
    same stock are correlated/overlapping (brief Sections 52-54). This is a
    genuinely new capability the notebook does not have; treat it as a first pass,
    not a rigorously reviewed inference procedure.
    """
    sub = event_df[[cluster_col, return_col]].dropna()
    if sub.empty:
        return {"n_clusters": 0, "mean": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    groups = {k: v[return_col].to_numpy() for k, v in sub.groupby(cluster_col)}
    tickers = list(groups.keys())
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        sampled_tickers = rng.choice(tickers, size=len(tickers), replace=True)
        pooled = np.concatenate([groups[t] for t in sampled_tickers])
        boot_means[b] = pooled.mean()
    alpha = 1 - ci
    lo, hi = np.quantile(boot_means, [alpha / 2, 1 - alpha / 2])
    return {
        "n_clusters": len(tickers),
        "n_observations": len(sub),
        "mean": float(sub[return_col].mean()),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "ci_level": ci,
        "method": "cluster_block_bootstrap_by_ticker",
    }
