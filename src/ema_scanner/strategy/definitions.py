"""Wires config-driven parameters into the four cluster-crossover Definitions
A-D (notebook Cell 20; audit row 20). The actual math lives in
features/cluster.py — this module is the strategy-layer entry point that
applies the configured `enabled` list and parameter overrides.
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.config import DefinitionsConfig
from ema_scanner.features.cluster import (
    definition_A_sequential_crossover,
    definition_B_alignment_transition,
    definition_C_price_through_cluster,
    definition_D_compression_then_expansion,
)

DEFINITION_COLS = {
    "A": "DefA_SequentialCrossover",
    "B": "DefB_AlignmentTransition",
    "C": "DefC_PriceThroughCluster",
    "D": "DefD_CompressionExpansion",
}


def compute_enabled_definitions(
    df: pd.DataFrame, state: pd.Series, cfg: DefinitionsConfig, suffix: str = ""
) -> pd.DataFrame:
    out = df.copy()
    if "A" in cfg.enabled:
        out["DefA_SequentialCrossover"] = definition_A_sequential_crossover(
            out, suffix=suffix, max_gap=cfg.sequential_crossover_max_gap_sessions
        )
    if "B" in cfg.enabled:
        out["DefB_AlignmentTransition"] = definition_B_alignment_transition(state)
    if "C" in cfg.enabled:
        out["DefC_PriceThroughCluster"] = definition_C_price_through_cluster(out, suffix=suffix)
    if "D" in cfg.enabled:
        out["DefD_CompressionExpansion"] = definition_D_compression_then_expansion(
            out, suffix=suffix, lookahead=cfg.compression_expansion_lookahead_days
        )
    return out
