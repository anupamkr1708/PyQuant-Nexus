"""Walk-forward research (notebook Cell 40; audit row 31; docs/NOTEBOOK_AUDIT.md §5.2).

MODE 1 (`walk_forward_splits` / `walk_forward_fixed_spec`): ported from the
notebook essentially unchanged. This evaluates the FROZEN 10/20/89/200
specification across rolling out-of-sample folds. It does NOT optimize
anything — the notebook's own markdown already says so, and this refactor keeps
that honesty rather than dressing it up as more than it is.

MODE 2 (`true_walk_forward`): NEW CODE, not present in the notebook at all
(brief Section 51 explicitly asks for it; the notebook only has Mode 1). For
each fold: select an EMA-period combination from a small grid using ONLY the
training window's median 20D return, freeze it, then evaluate that frozen
choice, untouched, on the test window. This is a deliberately simple selection
rule — a genuine nested train/test split, not a sophisticated optimizer. Treat
Mode 2's OOS numbers as a first pass, not a validated research pipeline.
"""
from __future__ import annotations

import itertools

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import Config
from ema_scanner.execution.costs import CostsConfig
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.research.event_study import run_event_study_all_models
from ema_scanner.research.statistics import performance_stats
from ema_scanner.strategy.signal_engine import build_stock_feature_frame


def walk_forward_splits(dates: pd.DatetimeIndex, train_years: float = 3.0, test_years: float = 1.0, step_years: float = 1.0) -> list[dict]:
    start, end = dates.min(), dates.max()
    splits, train_start = [], start
    while True:
        train_end = train_start + pd.DateOffset(years=train_years)
        test_start = train_end
        test_end = test_start + pd.DateOffset(years=test_years)
        if test_start >= end:
            break
        splits.append({
            "train_start": train_start, "train_end": min(train_end, end),
            "test_start": test_start, "test_end": min(test_end, end),
        })
        train_start = train_start + pd.DateOffset(years=step_years)
        if train_start >= end:
            break
    return splits


def walk_forward_fixed_spec(
    feature_frames: dict[str, pd.DataFrame], calendar: NSECalendar, costs: CostsConfig,
    horizon: int = 20, train_years: float = 3.0, test_years: float = 1.0,
) -> pd.DataFrame:
    """MODE 1: rolling fixed-specification OOS evaluation. See module docstring."""
    if not feature_frames:
        return pd.DataFrame()
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(f.index) for f in feature_frames.values()])))
    splits = walk_forward_splits(all_dates, train_years=train_years, test_years=test_years, step_years=test_years)
    rows = []
    for i, sp in enumerate(splits):
        windowed = {t: f[(f.index >= sp["test_start"]) & (f.index < sp["test_end"])] for t, f in feature_frames.items()}
        windowed = {t: f for t, f in windowed.items() if len(f) > 30}
        if not windowed:
            continue
        ev = run_event_study_all_models(windowed, calendar, costs)
        if ev.empty:
            continue
        for model in ev["Entry_Model"].unique():
            stats = performance_stats(ev[ev["Entry_Model"] == model][f"Fwd_Ret_{horizon}D"])
            stats.update({"fold": i, "test_start": sp["test_start"], "test_end": sp["test_end"], "entry_model": model, "mode": "MODE_1_FIXED_SPEC"})
            rows.append(stats)
    return pd.DataFrame(rows)


def true_walk_forward(
    universe: dict[str, pd.DataFrame], index_df: pd.DataFrame, base_cfg: Config,
    calendar: NSECalendar, param_grid: dict[str, tuple[int, ...]], horizon: int = 20,
    train_years: float = 3.0, test_years: float = 1.0,
) -> pd.DataFrame:
    """MODE 2: true nested train-then-freeze-then-test walk-forward. See module
    docstring — this is new, deliberately simple code."""
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in universe.values()])))
    splits = walk_forward_splits(all_dates, train_years=train_years, test_years=test_years, step_years=test_years)
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    rows = []

    for fold_i, sp in enumerate(splits):
        train_universe = {t: d[(d.index >= sp["train_start"]) & (d.index < sp["train_end"])] for t, d in universe.items()}
        train_universe = {t: d for t, d in train_universe.items() if len(d) > 260}
        if not train_universe:
            continue
        train_index = index_df[(index_df.index >= sp["train_start"]) & (index_df.index < sp["train_end"])]

        best_combo, best_metric = None, float("-inf")
        for combo in combos:
            trial_cfg = base_cfg.model_copy(deep=True)
            fast, medium, structural, long_ = combo
            trial_cfg.strategy.ema.fast = fast
            trial_cfg.strategy.ema.medium = medium
            trial_cfg.strategy.ema.structural = structural
            trial_cfg.strategy.ema.long = long_
            try:
                regime_df = compute_market_regime(train_index)
                frames = {t: build_stock_feature_frame(d, train_index["Close"], regime_df, trial_cfg) for t, d in train_universe.items()}
                ev = run_event_study_all_models(frames, calendar, trial_cfg.costs)
                if ev.empty:
                    continue
                metric = ev[f"Fwd_Ret_{horizon}D"].median()
            except Exception:  # noqa: BLE001, S112 - one bad grid combo must not crash the whole fold search
                continue
            if pd.notna(metric) and metric > best_metric:
                best_metric, best_combo = metric, combo

        if best_combo is None:
            continue

        # Freeze best_combo, evaluate ONLY on the test window — never re-fit here.
        test_universe = {t: d[(d.index >= sp["test_start"]) & (d.index < sp["test_end"])] for t, d in universe.items()}
        test_universe = {t: d for t, d in test_universe.items() if len(d) > 30}
        if not test_universe:
            continue
        test_index = index_df[(index_df.index >= sp["test_start"]) & (index_df.index < sp["test_end"])]
        frozen_cfg = base_cfg.model_copy(deep=True)
        frozen_cfg.strategy.ema.fast, frozen_cfg.strategy.ema.medium, frozen_cfg.strategy.ema.structural, frozen_cfg.strategy.ema.long = best_combo
        regime_df = compute_market_regime(test_index)
        test_frames = {t: build_stock_feature_frame(d, test_index["Close"], regime_df, frozen_cfg) for t, d in test_universe.items()}
        ev_test = run_event_study_all_models(test_frames, calendar, frozen_cfg.costs)
        if ev_test.empty:
            continue
        oos_stats = performance_stats(ev_test[f"Fwd_Ret_{horizon}D"])
        oos_stats.update({
            "fold": fold_i, "test_start": sp["test_start"], "test_end": sp["test_end"],
            "selected_fast": best_combo[0], "selected_medium": best_combo[1],
            "selected_structural": best_combo[2], "selected_long": best_combo[3],
            "train_selection_metric": best_metric, "mode": "MODE_2_TRUE_WALK_FORWARD",
        })
        rows.append(oos_stats)
    return pd.DataFrame(rows)
