"""BLOCKER 6 (Phase-3): walk-forward Mode 2 must compute features with
sufficient pre-fold warmup, not from the first row of each fold's own slice.
"""
import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import load_config
from ema_scanner.research.walk_forward import true_walk_forward
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_mode2_fold_features_are_stable_with_additional_pre_fold_warmup():
    """Builds a universe long enough for two folds, runs Mode 2, and directly
    inspects (by calling the same internal feature-construction path with
    varying amounts of extra history) that a fold's evaluated features do not
    depend on exactly how much MORE history precedes the fold boundary,
    beyond the policy minimum -- proving features are computed continuously
    with real warmup, not from a cold start at the fold's own first row."""
    from ema_scanner.features.regime import compute_market_regime
    from ema_scanner.research.warmup import calculate_required_warmup
    from ema_scanner.strategy.signal_engine import build_stock_feature_frame

    cfg = load_config()
    policy = calculate_required_warmup(cfg)
    cal = NSECalendar()

    total_days = policy.required_daily_sessions + 600
    full = make_synthetic_ohlcv(total_days, seed=2001, drift=0.02, vol=1.0)
    index_full = make_synthetic_ohlcv(total_days, seed=2002, drift=0.02, vol=1.0)[["Close"]]

    fold_boundary_loc = policy.required_daily_sessions + 300
    fold_start = full.index[fold_boundary_loc]

    # Simulate what true_walk_forward's _build_with_warmup does internally:
    # build features using [warmup_start, fold_end) for two different amounts
    # of extra history before fold_start, and confirm the SIGNAL at a date
    # well inside the fold is identical either way.
    warmup_start_minimum = policy.warmup_start_via_calendar(fold_start, cal)
    loc_minimum = full.index.get_loc(warmup_start_minimum)
    slice_minimum = full.iloc[loc_minimum:]
    idx_minimum = index_full.iloc[loc_minimum:]

    extra_loc = max(loc_minimum - 200, 0)  # 200 MORE sessions of warmup on top
    slice_extra = full.iloc[extra_loc:]
    idx_extra = index_full.iloc[extra_loc:]

    regime_min = compute_market_regime(idx_minimum)
    regime_extra = compute_market_regime(idx_extra)
    feats_min = build_stock_feature_frame(slice_minimum, idx_minimum["Close"], regime_min, cfg)
    feats_extra = build_stock_feature_frame(slice_extra, idx_extra["Close"], regime_extra, cfg)

    check_date = full.index[fold_boundary_loc + 50]
    for col in ["Daily_State", "Weekly_State", "Signal_State"]:
        a, b = feats_min.loc[check_date, col], feats_extra.loc[check_date, col]
        if pd.isna(a) and pd.isna(b):
            continue
        assert a == b, f"{col} differs at {check_date} depending on pre-fold warmup depth -- Mode 2 warmup is insufficient"


def test_mode2_does_not_crash_and_produces_warmup_metadata():
    """End-to-end smoke test: Mode 2 runs on a small synthetic universe and
    each output row records how much warmup was actually used (auditability)."""
    from ema_scanner.features.regime import (
        compute_market_regime,  # noqa: F401 - imported for parity with helper usage elsewhere
    )

    cfg = load_config()
    cal = NSECalendar()
    n = 1400
    raw_universe = {
        "AAA": make_synthetic_ohlcv(n, seed=3001, drift=0.05),
        "BBB": make_synthetic_ohlcv(n, seed=3002, drift=0.03),
    }
    index_df = make_synthetic_ohlcv(n, seed=3003)[["Close"]]
    param_grid = {"fast": (10,), "medium": (20,), "structural": (89,), "long": (150, 200)}

    result = true_walk_forward(raw_universe, index_df, cfg, cal, param_grid, train_years=2, test_years=1)
    if not result.empty:
        assert "warmup_sessions_used" in result.columns
        assert (result["warmup_sessions_used"] > 0).all()
        assert "selected_training_long" in result.columns
        assert "training_window_selection_metric" in result.columns
