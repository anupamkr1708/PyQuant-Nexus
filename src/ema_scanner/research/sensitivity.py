"""Parameter sensitivity / robustness (notebook Cell 42; audit row 32).

The purpose is NOT to find the highest-return parameter combination — it is to
check whether the strategy behaves reasonably across NEARBY parameter choices
(brief Sections 29-30, 58). `plateau_summary` reports the full grid distribution
alongside the single best cell specifically so a genuine plateau is
distinguishable from an overfit spike. 10/20/89/200 is never promoted as
"optimal" by this module or anywhere else in this codebase.
"""
from __future__ import annotations

import itertools

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import Config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.research.event_study import run_event_study_all_models
from ema_scanner.research.statistics import performance_stats
from ema_scanner.strategy.signal_engine import build_stock_feature_frame


def evaluate_param_grid(param_grid: dict, evaluate_fn, fixed_kwargs: dict | None = None) -> pd.DataFrame:
    fixed_kwargs = fixed_kwargs or {}
    keys = list(param_grid.keys())
    rows = []
    for combo in itertools.product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, combo))
        try:
            metrics = evaluate_fn(**params, **fixed_kwargs)
        except Exception as e:
            metrics = {"error": str(e)}
        rows.append({**params, **metrics})
    return pd.DataFrame(rows)


def plateau_summary(grid_df: pd.DataFrame, metric_col: str, param_cols: list[str]) -> dict:
    if metric_col not in grid_df.columns or grid_df[metric_col].dropna().empty:
        return {"note": "no valid metric values in grid"}
    vals = grid_df[metric_col].dropna()
    best_row = grid_df.loc[vals.idxmax()]
    return {
        "grid_size": len(grid_df), "metric_mean": float(vals.mean()), "metric_median": float(vals.median()),
        "metric_std": float(vals.std()), "metric_min": float(vals.min()), "metric_max": float(vals.max()),
        "best_params": {c: best_row[c] for c in param_cols}, "best_metric": float(best_row[metric_col]),
        "spread_best_minus_median": float(vals.max() - vals.median()),
    }


def ema_period_sensitivity(
    universe: dict[str, pd.DataFrame], index_df: pd.DataFrame, base_cfg: Config, calendar: NSECalendar,
    fast_grid=(8, 10, 12), medium_grid=(18, 20, 22), structural_grid=(80, 89, 100), long_grid=(180, 200, 220),
    horizon: int = 20, n_tickers_subset: int | None = None,
) -> pd.DataFrame:
    """Perturbs ONE EMA role at a time (holding the other three at the base spec),
    per the brief's plateau-not-optimum guidance (Section 29)."""
    if n_tickers_subset is not None:
        universe = {k: universe[k] for k in list(universe.keys())[:n_tickers_subset]}
    base = {
        "fast": base_cfg.strategy.ema.fast, "medium": base_cfg.strategy.ema.medium,
        "structural": base_cfg.strategy.ema.structural, "long": base_cfg.strategy.ema.long,
    }

    def evaluate(fast, medium, structural, long_):
        trial_cfg = base_cfg.model_copy(deep=True)
        trial_cfg.strategy.ema.fast, trial_cfg.strategy.ema.medium = fast, medium
        trial_cfg.strategy.ema.structural, trial_cfg.strategy.ema.long = structural, long_
        regime_df = compute_market_regime(
            index_df, ema_fast=trial_cfg.strategy.regime.index_ema_fast, ema_medium=trial_cfg.strategy.regime.index_ema_medium,
            ema_structural=trial_cfg.strategy.regime.index_ema_structural, ema_long=trial_cfg.strategy.regime.index_ema_long,
        )
        frames = {}
        for ticker, daily_df in universe.items():
            try:
                frames[ticker] = build_stock_feature_frame(daily_df, index_df["Close"], regime_df, trial_cfg, calendar=calendar)
            except Exception:  # noqa: BLE001 - one bad ticker must not crash the whole sensitivity grid
                continue
        if not frames:
            return {"n_trades": 0, "avg_return_pct": float("nan")}
        ev = run_event_study_all_models(frames, calendar, trial_cfg.costs)
        if ev.empty:
            return {"n_trades": 0, "avg_return_pct": float("nan")}
        stats = performance_stats(ev[f"Fwd_Ret_{horizon}D"])
        return {"n_trades": stats.get("n_trades", 0), "avg_return_pct": stats.get("avg_return_pct", float("nan"))}

    rows = []
    for f in fast_grid:
        rows.append({"perturbed_param": "fast", **evaluate(f, base["medium"], base["structural"], base["long"]),
                     "fast": f, "medium": base["medium"], "structural": base["structural"], "long": base["long"]})
    for m in medium_grid:
        rows.append({"perturbed_param": "medium", **evaluate(base["fast"], m, base["structural"], base["long"]),
                     "fast": base["fast"], "medium": m, "structural": base["structural"], "long": base["long"]})
    for s in structural_grid:
        rows.append({"perturbed_param": "structural", **evaluate(base["fast"], base["medium"], s, base["long"]),
                     "fast": base["fast"], "medium": base["medium"], "structural": s, "long": base["long"]})
    for l in long_grid:
        rows.append({"perturbed_param": "long", **evaluate(base["fast"], base["medium"], base["structural"], l),
                     "fast": base["fast"], "medium": base["medium"], "structural": base["structural"], "long": l})
    return pd.DataFrame(rows)
