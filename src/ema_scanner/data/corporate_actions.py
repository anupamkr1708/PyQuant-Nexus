"""Corporate actions interface (brief Section 21).

Formalizes the interface for split/bonus/rights/merger/symbol-change handling.
The notebook does not implement corporate-action-specific logic beyond
whatever adjustment yfinance's `AdjClose` already encodes; this module does
not invent a fuller model. It exists so a real corporate-actions data source
can be plugged in later without touching the feature/strategy layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    date: str
    kind: Literal["SPLIT", "BONUS", "RIGHTS", "MERGER", "SYMBOL_CHANGE", "DELISTING"]
    ratio: float | None = None  # e.g. split 1:5 -> 0.2, bonus 1:1 -> 0.5 (interpretation documented per kind)
    new_symbol: str | None = None  # for SYMBOL_CHANGE / MERGER
    note: str | None = None


class CorporateActionsProvider:
    """NOT IMPLEMENTED beyond the interface — no corporate-actions data source
    is wired up in this refactor (consistent with the notebook, which also has
    none beyond whatever yfinance's AdjClose implicitly encodes). Formalized
    here so it can be added later (brief Section 21) without a redesign."""

    def get_actions(self, symbol: str, start_date: str, end_date: str) -> list[CorporateAction]:
        raise NotImplementedError("No corporate-actions data source is configured.")
