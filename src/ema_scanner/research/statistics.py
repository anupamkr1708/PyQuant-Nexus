"""Performance statistics (notebook Cell 38; audit row 30; Phase-2 Section 15 -- BLOCKER).

Two DISTINCT statistic families, never mixed (Phase-2 Section 15):

    EVENT_STUDY_STATS   -- performance_stats(), performance_stats_by_group()
    PORTFOLIO_STATS     -- portfolio_stats_from_equity_curve()

EMPIRICALLY TESTED RESULT (methodology): descriptive statistics of a historical
sample, never a guarantee of future performance (brief Section 102). Includes a
block-bootstrap confidence interval, which the notebook does NOT have (brief
Section 54) -- new code, kept simple and clustered by ticker to acknowledge
overlapping/correlated signals rather than assuming iid observations (brief
Section 52-54).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def performance_stats(returns_pct: pd.Series) -> dict:
    """EVENT_STUDY_STATS (Phase-2 Section 15 -- BLOCKER fix): descriptive
    statistics of a set of (possibly overlapping, non-chronological) event
    returns. **Deliberately does NOT compute a drawdown.** A drawdown
    requires a time-ordered, mutually-exclusive equity path; event returns
    are neither (multiple stocks can signal the same day; the same stock can
    have overlapping holding windows). v1 computed "max_drawdown_pct" here
    from `cumprod(1+r)` in whatever order the events happened to be listed --
    not a meaningful portfolio drawdown. See `portfolio_stats_from_equity_curve`
    for the real, chronologically-correct version used by the backtest engine.
    """
    r = returns_pct.dropna()
    if len(r) == 0:
        return {"n_trades": 0}
    wins, losses = r[r > 0], r[r <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else np.nan
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


def portfolio_stats_from_equity_curve(equity_curve: pd.DataFrame, trade_log: pd.DataFrame | None = None) -> dict:
    """PORTFOLIO_STATS (Phase-2 Section 15): computed from the ACTUAL
    time-ordered equity curve produced by research/backtest.py -- CAGR,
    annualized volatility, Sharpe, Sortino, Calmar, max drawdown, max
    drawdown duration, average exposure, and (if a trade log is supplied)
    profit factor / trade expectancy / a turnover proxy. This is the only
    place in the codebase that computes a "max drawdown" claiming to
    represent an actual tradable path."""
    if equity_curve.empty or "equity" not in equity_curve.columns:
        return {"n_sessions": 0}
    eq = equity_curve["equity"].astype(float)
    n = len(eq)
    daily_ret = eq.pct_change().dropna()

    running_max = eq.cummax()
    drawdown = (eq / running_max - 1.0) * 100.0
    max_dd = float(drawdown.min()) if n else np.nan

    underwater = drawdown < -1e-9
    max_dd_duration, current_run = 0, 0
    for u in underwater:
        current_run = current_run + 1 if u else 0
        max_dd_duration = max(max_dd_duration, current_run)

    years = n / 252.0 if n > 0 else np.nan
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0) * 100.0 if n > 1 and years and years > 0 and eq.iloc[0] > 0 else np.nan
    ann_vol = float(daily_ret.std() * np.sqrt(252) * 100.0) if len(daily_ret) > 1 else np.nan
    sharpe = float((daily_ret.mean() * 252) / (daily_ret.std() * np.sqrt(252))) if len(daily_ret) > 1 and daily_ret.std() > 0 else np.nan
    downside = daily_ret[daily_ret < 0]
    sortino = float((daily_ret.mean() * 252) / (downside.std() * np.sqrt(252))) if len(downside) > 1 and downside.std() > 0 else np.nan
    calmar = float(cagr / abs(max_dd)) if pd.notna(cagr) and pd.notna(max_dd) and max_dd < 0 else np.nan
    avg_exposure_pct = float((equity_curve["positions_value"] / eq).mean() * 100.0) if "positions_value" in equity_curve.columns else np.nan

    out = {
        "n_sessions": n, "cagr_pct": float(cagr) if pd.notna(cagr) else np.nan,
        "annualized_volatility_pct": ann_vol, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "max_drawdown_pct": max_dd, "max_drawdown_duration_sessions": max_dd_duration,
        "avg_exposure_pct": avg_exposure_pct,
        "final_equity": float(eq.iloc[-1]) if n else np.nan, "initial_equity": float(eq.iloc[0]) if n else np.nan,
    }
    if trade_log is not None and not trade_log.empty and "net_pnl" in trade_log.columns:
        wins = trade_log[trade_log["net_pnl"] > 0]["net_pnl"]
        losses = trade_log[trade_log["net_pnl"] <= 0]["net_pnl"]
        gross_win, gross_loss = wins.sum(), -losses.sum()
        out["trade_count"] = len(trade_log)
        out["win_rate_pct"] = float(len(wins) / len(trade_log) * 100.0) if len(trade_log) else np.nan
        out["profit_factor"] = float(gross_win / gross_loss) if gross_loss > 0 else np.nan
        out["expectancy_per_trade"] = float(trade_log["net_pnl"].mean())
        out["turnover_trades_per_year"] = float(len(trade_log) / years) if years and years > 0 else np.nan
    return out


def block_bootstrap_ci(
    event_df: pd.DataFrame, return_col: str, cluster_col: str = "Ticker",
    n_boot: int = 2000, ci: float = 0.95, seed: int = 42,
) -> dict:
    """Cluster (block) bootstrap CI for the mean of `return_col`, resampling whole
    tickers with replacement rather than individual rows, since signals from the
    same stock are correlated/overlapping (brief Sections 52-54). This is a
    genuinely new capability the notebook does not have; treat it as a first pass,
    not a rigorously reviewed inference procedure. It addresses SAME-SYMBOL
    clustering but NOT same-date cross-sectional clustering (many stocks
    signaling on one market-wide day) -- see docs/RESEARCH_LIMITATIONS.md.
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
        "n_clusters": len(tickers), "n_observations": len(sub), "mean": float(sub[return_col].mean()),
        "ci_low": float(lo), "ci_high": float(hi), "ci_level": ci,
        "method": "cluster_block_bootstrap_by_ticker",
    }
