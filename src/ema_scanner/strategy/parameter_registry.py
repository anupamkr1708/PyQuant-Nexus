"""Machine-auditable parameter classification registry (Phase-2 Section 23).

**Bug fixed:** v1 only labeled parameter categories (SOURCE_DERIVED_RULE /
RESEARCH_HYPOTHESIS / OPTIONAL_FILTER / etc.) as YAML *comments* in
configs/default.yaml -- human-readable, but not machine-auditable: nothing in
the running system could answer "what category is
`strategy.cluster.compression_percentile`?" at runtime. This registry is the
actual runtime source of truth; `show-config` and the run manifest both read
it, so the classification travels with every run rather than living only in a
file a human might not open.

Deliberately a flat dict, not a class hierarchy or schema-validation
framework -- the brief's own instruction (Phase-2 preamble) is not to
overengineer this.
"""
from __future__ import annotations

PARAMETER_CATEGORIES: dict[str, str] = {
    "strategy.ema.fast": "SOURCE_DERIVED_RULE",
    "strategy.ema.medium": "SOURCE_DERIVED_RULE",
    "strategy.ema.structural": "SOURCE_DERIVED_RULE",
    "strategy.ema.long": "SOURCE_DERIVED_RULE",
    "strategy.ema.seed_method": "MATHEMATICAL_DEFINITION",
    "strategy.swing.left_bars": "ENGINEERING_PARAMETER",
    "strategy.swing.right_bars": "ENGINEERING_PARAMETER",
    "strategy.volatility.atr_period": "SOURCE_DERIVED_RULE",
    "strategy.cluster.width_lookback": "RESEARCH_HYPOTHESIS",
    "strategy.cluster.compression_percentile": "RESEARCH_HYPOTHESIS",
    "strategy.cluster.expansion_percentile": "RESEARCH_HYPOTHESIS",
    "strategy.cluster.flat_band_percentile": "RESEARCH_HYPOTHESIS",
    "strategy.definitions.sequential_crossover_max_gap_sessions": "RESEARCH_HYPOTHESIS",
    "strategy.definitions.compression_expansion_lookahead_days": "RESEARCH_HYPOTHESIS",
    "strategy.pullback.shallow_atr": "RESEARCH_HYPOTHESIS",
    "strategy.pullback.moderate_atr": "RESEARCH_HYPOTHESIS",
    "strategy.pullback.deep_atr": "RESEARCH_HYPOTHESIS",
    "strategy.pullback.breakout_memory_bars": "ENGINEERING_PARAMETER",
    "strategy.regime.benchmark": "ENGINEERING_DECISION",
    "strategy.relative_strength.windows": "SOURCE_DERIVED_RULE",
    "strategy.liquidity.enabled": "OPTIONAL_FILTER",
    "data.price_mode": "ENGINEERING_DECISION",
    "data.max_stale_sessions": "ENGINEERING_PARAMETER",
    "data.primary_provider": "ENGINEERING_DECISION",
    "calendar.eod_data_cutoff": "ENGINEERING_DECISION",
    "execution.model": "ENGINEERING_DECISION",
    "risk.risk_per_trade_pct": "OPTIONAL_PARAMETER",
    "risk.atr_stop_multiple": "OPTIONAL_PARAMETER",
    "costs.brokerage_pct": "PLACEHOLDER_UNVERIFIED",
    "costs.stt_pct": "PLACEHOLDER_UNVERIFIED",
    "costs.exchange_charges_pct": "PLACEHOLDER_UNVERIFIED",
    "costs.gst_pct": "PLACEHOLDER_UNVERIFIED",
    "research.backtest.exit_rule": "RESEARCH_HYPOTHESIS",
    "research.backtest.initial_capital": "ENGINEERING_PARAMETER",
    "research.backtest.max_concurrent_positions": "ENGINEERING_PARAMETER",
}


def classify(dotted_path: str) -> str:
    return PARAMETER_CATEGORIES.get(dotted_path, "UNCLASSIFIED")


def classify_all() -> dict[str, str]:
    """Returns the full registry -- used by `show-config` and the run
    manifest so the classification is visible at runtime, not just in a YAML
    comment a human might not read."""
    return dict(PARAMETER_CATEGORIES)
