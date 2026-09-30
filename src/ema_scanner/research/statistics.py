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


def portfolio_stats_from_equity_curve(
    equity_curve: pd.DataFrame, trade_log: pd.DataFrame | None = None,
    risk_free_rate_annual: float = 0.0, mar_annual: float = 0.0,
) -> dict:
    """PORTFOLIO_STATS (Phase-2 Section 15; Phase-3 BLOCKERS 18, 19): computed
    from the ACTUAL time-ordered equity curve produced by research/backtest.py.

    **Phase-3 BLOCKER 19 -- formulas made explicit, not just relabeled:**

    - **CAGR** uses EXACT elapsed calendar days between the equity curve's
      first and last DATES (`(last - first).days / 365.25`), not merely
      `n_sessions / 252` -- the two agree closely for a full, gap-free daily
      series but diverge if the curve has an irregular session count (e.g.
      holidays already excluded, or a partial period).
    - **Sharpe** = `(mean_daily_return * 252 - risk_free_rate_annual) /
      (daily_return_std * sqrt(252))`. `risk_free_rate_annual` defaults to
      0.0 -- an explicit, documented ENGINEERING_DECISION, not a claim that
      the true risk-free rate is zero. Pass a real annualized risk-free rate
      (e.g. the prevailing T-bill/repo rate) for a rigorous Sharpe.
    - **Sortino**'s downside deviation is computed relative to `mar_annual`
      (minimum acceptable return, default 0.0, i.e. MAR = risk-free-equivalent
      of "capital preservation"), converted to a per-day threshold
      (`mar_annual / 252`) -- returns ABOVE the MAR are excluded from the
      downside deviation calculation, which is the standard Sortino
      definition (not simply "all negative returns", though with the
      default `mar_annual=0.0` the two happen to coincide).
    - **Calmar** = `CAGR / abs(max_drawdown_pct)`.
    - **Max drawdown duration** = longest consecutive run of sessions with
      `equity < running_peak`.

    **Phase-3 BLOCKER 18 -- turnover fixed:** the old `turnover_trades_per_year`
    name conflated TRADE COUNT with TURNOVER (a notional/equity ratio). Now:
    `trade_frequency_per_year` (unambiguously trade-count-based) and
    `notional_turnover_pct` (`sum(abs(trade notional)) / average portfolio
    equity * 100`, the standard notional-turnover definition) are reported
    SEPARATELY.

    See tests/unit/test_portfolio_stats_formulas.py for a deterministic
    fixture with hand-computed expected values for every formula above.
    """
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

    # BLOCKER 19: exact elapsed calendar days, not a session-count approximation.
    if n > 1 and isinstance(eq.index, pd.DatetimeIndex):
        elapsed_days = (eq.index[-1] - eq.index[0]).days
        years = elapsed_days / 365.25 if elapsed_days > 0 else np.nan
    else:
        years = (n - 1) / 252.0 if n > 1 else np.nan
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0) * 100.0 if n > 1 and years and years > 0 and eq.iloc[0] > 0 else np.nan

    ann_vol = float(daily_ret.std() * np.sqrt(252) * 100.0) if len(daily_ret) > 1 else np.nan
    sharpe = (
        float((daily_ret.mean() * 252 - risk_free_rate_annual) / (daily_ret.std() * np.sqrt(252)))
        if len(daily_ret) > 1 and daily_ret.std() > 0 else np.nan
    )
    mar_daily = mar_annual / 252.0
    downside = daily_ret[daily_ret < mar_daily]
    sortino = (
        float((daily_ret.mean() * 252 - mar_annual) / (downside.std() * np.sqrt(252)))
        if len(downside) > 1 and downside.std() > 0 else np.nan
    )
    calmar = float(cagr / abs(max_dd)) if pd.notna(cagr) and pd.notna(max_dd) and max_dd < 0 else np.nan
    avg_exposure_pct = float((equity_curve["positions_value"] / eq).mean() * 100.0) if "positions_value" in equity_curve.columns else np.nan

    out = {
        "n_sessions": n, "cagr_pct": float(cagr) if pd.notna(cagr) else np.nan,
        "annualized_volatility_pct": ann_vol, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "risk_free_rate_annual": risk_free_rate_annual, "mar_annual": mar_annual,
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
        # BLOCKER 18: trade COUNT frequency, explicitly NOT called "turnover".
        out["trade_frequency_per_year"] = float(len(trade_log) / years) if years and years > 0 else np.nan
        # BLOCKER 18: TRUE notional turnover = sum(|trade notional|) / average equity.
        if "entry_price" in trade_log.columns and "quantity" in trade_log.columns:
            notional = (trade_log["entry_price"].astype(float) * trade_log["quantity"].astype(float)).abs().sum()
            avg_equity = float(eq.mean()) if n else np.nan
            out["notional_turnover_pct"] = float(notional / avg_equity * 100.0) if avg_equity and avg_equity > 0 else np.nan
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
    signaling on one market-wide day) -- see `block_bootstrap_ci_by_date` and
    `two_way_cluster_bootstrap_ci` below (Phase-3 BLOCKER 20) for that second
    dependence dimension.
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


def block_bootstrap_ci_by_date(
    event_df: pd.DataFrame, return_col: str, date_col: str = "Execution_Date",
    n_boot: int = 2000, ci: float = 0.95, seed: int = 42,
) -> dict:
    """Phase-3 BLOCKER 20: the SAME clustered-bootstrap mechanism as
    `block_bootstrap_ci`, but resampling whole EXECUTION DATES with
    replacement instead of whole tickers -- addresses the OTHER dependence
    dimension the ticker-clustered version misses: many stocks can signal on
    the same market-wide day (a strategy-wide regime effect), which is not
    independence across observations even when spread across many tickers."""
    sub = event_df[[date_col, return_col]].dropna()
    if sub.empty:
        return {"n_clusters": 0, "mean": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    groups = {k: v[return_col].to_numpy() for k, v in sub.groupby(date_col)}
    dates = list(groups.keys())
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        sampled_dates_idx = rng.integers(0, len(dates), size=len(dates))
        pooled = np.concatenate([groups[dates[i]] for i in sampled_dates_idx])
        boot_means[b] = pooled.mean()
    alpha = 1 - ci
    lo, hi = np.quantile(boot_means, [alpha / 2, 1 - alpha / 2])
    return {
        "n_clusters": len(dates), "n_observations": len(sub), "mean": float(sub[return_col].mean()),
        "ci_low": float(lo), "ci_high": float(hi), "ci_level": ci,
        "method": "cluster_block_bootstrap_by_date",
    }


def two_way_cluster_bootstrap_ci(
    event_df: pd.DataFrame, return_col: str, cluster_col: str = "Ticker", date_col: str = "Execution_Date",
    n_boot: int = 2000, ci: float = 0.95, seed: int = 42,
) -> dict:
    """Phase-3 BLOCKER 20: an explicit, DOCUMENTED two-way dependence method --
    NOT a rigorous multi-way cluster-robust estimator (a proper two-way
    cluster-robust variance formula, e.g. Cameron-Gelbach-Miller-style, is NOT
    implemented here). This intersects independently-resampled ticker and
    date index sets per bootstrap replicate (falling back to the ticker-only
    resample when the intersection is empty) and reports the two-way estimate
    ALONGSIDE both single-way CIs and their combined widest bound, so a
    reader is never misled into thinking cross-sectional + serial dependence
    has been fully solved -- see docs/RESEARCH_LIMITATIONS.md.
    """
    sub = event_df[[cluster_col, date_col, return_col]].dropna()
    if sub.empty:
        return {"n_observations": 0, "mean": np.nan}

    ticker_result = block_bootstrap_ci(sub, return_col, cluster_col, n_boot, ci, seed)
    date_result = block_bootstrap_ci_by_date(sub, return_col, date_col, n_boot, ci, seed + 1)

    ticker_groups = {k: v.index.to_numpy() for k, v in sub.groupby(cluster_col)}
    date_groups = {k: v.index.to_numpy() for k, v in sub.groupby(date_col)}
    tickers, dates = list(ticker_groups.keys()), list(date_groups.keys())
    values_by_index = sub[return_col]
    rng = np.random.default_rng(seed + 2)
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        sampled_tickers = [tickers[i] for i in rng.integers(0, len(tickers), size=len(tickers))]
        ticker_idx = np.concatenate([ticker_groups[t] for t in sampled_tickers])
        sampled_dates = [dates[i] for i in rng.integers(0, len(dates), size=len(dates))]
        date_idx = np.concatenate([date_groups[d] for d in sampled_dates])
        combined_idx = np.intersect1d(ticker_idx, date_idx)
        if len(combined_idx) == 0:
            combined_idx = np.unique(ticker_idx)
        boot_means[b] = values_by_index.loc[np.unique(combined_idx)].mean()
    alpha = 1 - ci
    lo, hi = np.quantile(boot_means, [alpha / 2, 1 - alpha / 2])

    return {
        "n_observations": len(sub), "mean": float(sub[return_col].mean()),
        "two_way_ci_low": float(lo), "two_way_ci_high": float(hi), "ci_level": ci,
        "ticker_only_ci_low": ticker_result["ci_low"], "ticker_only_ci_high": ticker_result["ci_high"],
        "date_only_ci_low": date_result["ci_low"], "date_only_ci_high": date_result["ci_high"],
        "widest_ci_low": float(min(lo, ticker_result["ci_low"], date_result["ci_low"])),
        "widest_ci_high": float(max(hi, ticker_result["ci_high"], date_result["ci_high"])),
        "method": "two_way_cluster_bootstrap_approximate_NOT_a_rigorous_multiway_estimator",
    }
