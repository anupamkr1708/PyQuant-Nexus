"""THE master per-stock feature pipeline (notebook Cell 36's `build_stock_feature_frame`;
audit row 28). Reused UNCHANGED by the live scanner, the event study, and
walk-forward research, so all three evaluate identical feature definitions
(brief Section 106: exchange calendar -> point-in-time date -> universe -> raw
data -> quality -> normalization -> features -> EMA/alignment/crossovers ->
weekly context -> cluster -> swings -> pullback -> regime/RS/liquidity ->
strategy triggers -> optional filters -> risk/stop -> execution reference -> signal).

DATA_AVAILABLE_AT <= DECISION_TIME is the invariant this whole module exists to
protect (brief Section 73). Every function called here that touches time
(weekly, swings) already enforces its own no-lookahead rule at the feature
level (features/weekly.py, features/swing.py) — this module does not
re-implement those rules, it only assembles their outputs.
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.calendar.nse import NSECalendar
from ema_scanner.config import Config
from ema_scanner.execution.stops import compute_stops
from ema_scanner.features.alignment import classify_alignment, compute_mtf_matrix
from ema_scanner.features.cluster import (
    compute_cluster_compression,
    compute_cluster_expansion,
    compute_cluster_metrics,
)
from ema_scanner.features.crossover import compute_all_crossovers
from ema_scanner.features.ema import compute_all_emas
from ema_scanner.features.liquidity import compute_liquidity_diagnostics
from ema_scanner.features.pullback import classify_pullback
from ema_scanner.features.regime import attach_market_regime_asof
from ema_scanner.features.relative_strength import compute_relative_strength
from ema_scanner.features.swing import detect_swing_points
from ema_scanner.features.volatility import compute_atr, compute_ema_slopes
from ema_scanner.features.weekly import attach_last_known_weekly, build_true_weekly_ohlc
from ema_scanner.strategy.definitions import compute_enabled_definitions
from ema_scanner.strategy.entries import compute_all_entry_models
from ema_scanner.strategy.state_machine import compute_signal_state


def build_stock_feature_frame(
    daily_ohlc: pd.DataFrame,
    index_close_aligned: pd.Series,
    regime_df: pd.DataFrame,
    cfg: Config,
    calendar: NSECalendar | None = None,
) -> pd.DataFrame:
    s = cfg.strategy
    daily = daily_ohlc.sort_index().copy()

    # --- Daily EMA / alignment / crossovers ---
    d = compute_all_emas(daily, suffix="", ema_cfg=s.ema)

    # --- Weekly context (calendar-aware grouping, corrected availability rule) ---
    expected_week_ends = calendar.expected_week_ends(daily.index.min(), daily.index.max()) if calendar is not None else None
    weekly = build_true_weekly_ohlc(daily, expected_week_ends=expected_week_ends)
    w = compute_all_emas(weekly, suffix="_W", ema_cfg=s.ema)
    weekly_cols_present = [c for c in ["EMA10_W", "EMA20_W", "EMA89_W", "EMA200_W"] if c in w.columns]
    d = attach_last_known_weekly(d, w, weekly_cols_present)

    d = compute_all_crossovers(d, suffix="")
    d["Daily_State"] = classify_alignment(d["EMA10"], d["EMA20"], d["EMA89"], d["EMA200"])
    d["Weekly_State"] = classify_alignment(d["EMA10_W"], d["EMA20_W"], d["EMA89_W"], d["EMA200_W"])
    d["MTF_State"] = compute_mtf_matrix(d["Weekly_State"], d["Daily_State"])

    # --- Cluster metrics + Definitions A-D ---
    d = compute_cluster_metrics(d, suffix="")
    d = compute_cluster_compression(
        d, suffix="", lookback=s.cluster.width_lookback,
        compression_pctl=s.cluster.compression_percentile, expansion_pctl=s.cluster.expansion_percentile,
        min_periods=s.cluster.percentile_min_periods,
    )
    d = compute_cluster_expansion(
        d, suffix="", lookback=s.cluster.width_lookback, flat_band_pctl=s.cluster.flat_band_percentile,
        slope_lookback_days=s.cluster.width_slope_lookback_days, min_periods=s.cluster.percentile_min_periods,
    )
    d = compute_ema_slopes(d, suffix="", k=s.volatility.ema_slope_lookback_days)
    d = compute_enabled_definitions(d, d["Daily_State"], s.definitions, suffix="")

    # --- ATR / swings / pullback ---
    d = compute_atr(d, period=s.volatility.atr_period)
    swing = detect_swing_points(d, left=s.swing.left_bars, right=s.swing.right_bars)
    d["Is_Swing_Low"], d["Is_Swing_High"] = swing["Is_Swing_Low"], swing["Is_Swing_High"]
    d["Pullback_State"] = classify_pullback(
        d, atr_col=f"ATR{s.volatility.atr_period}", suffix="",
        shallow_atr=s.pullback.shallow_atr, moderate_atr=s.pullback.moderate_atr,
        deep_atr=s.pullback.deep_atr, breakout_memory_bars=s.pullback.breakout_memory_bars,
    )

    # --- Entry models A-E ---
    d = compute_all_entry_models(d, swing, d["Daily_State"], d["Pullback_State"], suffix="", enabled=tuple(s.entries.enabled))
    entry_cols = [c for c in [
        "EntryA_FreshAlignment", "EntryB_ClusterBreakout", "EntryC_PullbackContinuation",
        "EntryD_SwingHighBreakout", "EntryE_ReclaimAfterPullback",
    ] if c in d.columns]
    d["Any_Entry_Triggered"] = d[entry_cols].any(axis=1) if entry_cols else False

    # --- Risk / stops (swing-based primary, ATR-based separate diagnostic) ---
    d = compute_stops(d, swing, atr_col=f"ATR{s.volatility.atr_period}", atr_stop_multiple=cfg.risk.atr_stop_multiple)

    # --- Structural / optional-filter diagnostics (reported, never auto-enforced here) ---
    d["Price_vs_EMA200"] = d["Close"] > d["EMA200"]
    d["EMA89_vs_EMA200"] = d["EMA89"] > d["EMA200"]
    d["EMA200_Rising"] = d["EMA200"].diff(5) > 0

    # --- Regime / relative strength / liquidity ---
    d["Market_Regime"] = attach_market_regime_asof(d, regime_df)
    rs = compute_relative_strength(d["Close"], index_close_aligned.reindex(d.index, method="ffill"), windows=tuple(s.relative_strength.windows))
    d = pd.concat([d, rs], axis=1)
    d = compute_liquidity_diagnostics(
        d, volume_window_fast=s.liquidity.volume_window_fast_days, volume_window_slow=s.liquidity.volume_window_slow_days,
    )

    # --- Signal state machine (deterministic, see state_machine.py precedence docs) ---
    d["Signal_State"] = compute_signal_state(d["Daily_State"], d["Pullback_State"], d["Any_Entry_Triggered"], d["Cluster_Expansion_State"])
    return d
