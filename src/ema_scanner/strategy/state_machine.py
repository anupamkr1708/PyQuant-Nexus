"""Signal state machine (notebook Cell 36; audit row 28).

Deterministic, fully-reproducible lifecycle label — NOT a hidden ML classifier
(brief Section 37). Precedence is deliberately ordered (brief Section 83): later
assignments in `compute_signal_state` win over earlier ones, in this fixed order:

    WATCH -> TREND_FORMING -> BULLISH_CLUSTER -> PULLBACK -> TREND_FAILURE -> ENTRY_TRIGGERED

i.e. an entry trigger always wins the label even if the stock is simultaneously
in a pullback state; TREND_FAILURE beats a generic PULLBACK label but loses to an
actual entry trigger on the same bar. This precedence is unchanged from the
notebook and is now documented explicitly rather than left implicit in
assignment order.
"""
from __future__ import annotations

import pandas as pd

from ema_scanner.features.alignment import STATE_BULLISH_ALIGNED

SIGNAL_STATES = [
    "WATCH", "TREND_FORMING", "BULLISH_CLUSTER", "PULLBACK", "ENTRY_TRIGGERED",
    "IN_POSITION_RESEARCH_STATE", "TREND_CONTINUATION", "TREND_FAILURE",
    "EXIT_TRIGGER", "INVALIDATED",
]


def compute_signal_state(
    daily_state: pd.Series, pullback_state: pd.Series, any_entry_triggered: pd.Series, cluster_expansion: pd.Series
) -> pd.Series:
    out = pd.Series("WATCH", index=daily_state.index)
    out[daily_state == STATE_BULLISH_ALIGNED] = "TREND_FORMING"
    out[(daily_state == STATE_BULLISH_ALIGNED) & (cluster_expansion == "EXPANDING")] = "BULLISH_CLUSTER"
    out[pullback_state.isin(["SHALLOW_PULLBACK", "MODERATE_PULLBACK", "DEEP_PULLBACK"])] = "PULLBACK"
    out[pullback_state == "TREND_FAILURE"] = "TREND_FAILURE"
    out[any_entry_triggered] = "ENTRY_TRIGGERED"
    out[daily_state.isna()] = None
    return out
