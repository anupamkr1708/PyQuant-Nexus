"""Warm-up invariance test (Phase-2 Section 9 -- BLOCKER, Section 31).

Proves that once enough prior warm-up history is supplied, features inside
the evaluation window converge and no longer meaningfully depend on exactly
how much MORE history was supplied before the requested start.
"""
import numpy as np

from ema_scanner.config import load_config
from ema_scanner.features.regime import compute_market_regime
from ema_scanner.research.warmup import calculate_required_warmup
from ema_scanner.strategy.signal_engine import build_stock_feature_frame
from tests.fixtures.synthetic import make_synthetic_ohlcv


def test_extra_warmup_beyond_the_policy_minimum_does_not_change_evaluation_window_features():
    cfg = load_config()
    policy = calculate_required_warmup(cfg)

    # Build one long synthetic series once, then slice two different "warmup
    # starts" from it: one at exactly the policy minimum before the
    # evaluation window, one with 200 EXTRA sessions of warmup on top.
    total_days = policy.required_daily_sessions + 500 + 300
    full = make_synthetic_ohlcv(total_days, seed=999, drift=0.02, vol=1.0)
    index_full = make_synthetic_ohlcv(total_days, seed=998, drift=0.02, vol=1.0)[["Close"]]

    eval_start_loc = policy.required_daily_sessions + 200  # leaves >= policy minimum before eval start either way
    slice_minimum = full.iloc[200:]        # policy-minimum warmup before eval_start_loc
    slice_extra = full.iloc[0:]            # +200 extra sessions of warmup
    idx_minimum = index_full.iloc[200:]
    idx_extra = index_full.iloc[0:]

    regime_minimum = compute_market_regime(idx_minimum)
    regime_extra = compute_market_regime(idx_extra)

    feats_minimum = build_stock_feature_frame(slice_minimum, idx_minimum["Close"], regime_minimum, cfg)
    feats_extra = build_stock_feature_frame(slice_extra, idx_extra["Close"], regime_extra, cfg)

    eval_date = full.index[eval_start_loc + 100]  # well inside the evaluation window for both
    compare_cols = ["EMA200", "EMA20_W" if "EMA20_W" in feats_minimum.columns else "EMA200",
                    "Cluster_Width_Pct", "ATR14"]
    for col in dict.fromkeys(compare_cols):  # dedupe, preserve order
        a = float(feats_minimum.loc[eval_date, col])
        b = float(feats_extra.loc[eval_date, col])
        if np.isnan(a) and np.isnan(b):
            continue
        rel_diff = abs(a - b) / (abs(b) + 1e-9)
        assert rel_diff < 0.01, f"{col} differs by {rel_diff:.4%} between warmup lengths at {eval_date} -- warmup policy may be insufficient"


def test_warmup_policy_scales_with_configured_ema_long_period():
    from ema_scanner.config import Config

    small_cfg = Config()
    small_cfg.strategy.ema.long = 50
    large_cfg = Config()
    large_cfg.strategy.ema.long = 400
    small_policy = calculate_required_warmup(small_cfg)
    large_policy = calculate_required_warmup(large_cfg)
    assert large_policy.required_daily_sessions > small_policy.required_daily_sessions
