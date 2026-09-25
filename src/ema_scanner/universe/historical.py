"""Point-in-time historical universe (brief Section 24; docs/NOTEBOOK_AUDIT.md §2 pt 2).

The notebook has NO historical NIFTY-200-membership data source wired up and
says so explicitly in its own markdown. This module formalizes that gap as an
interface rather than fabricating membership history (brief Section 24: "Never
fabricate historical constituent membership.").
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ema_scanner.universe.models import UniverseConstituent


class PointInTimeUniverseProvider(ABC):
    """Interface for a FUTURE data source. No implementation ships with this
    refactor — see RESEARCH_LIMITATIONS.md."""

    @abstractmethod
    def constituents_as_of(self, as_of_date: str) -> list[UniverseConstituent]:
        raise NotImplementedError


def label_universe_mode(point_in_time_provider: PointInTimeUniverseProvider | None) -> str:
    """Mirrors the notebook's own `label_universe_mode()` (audit row 13):
    without a real point-in-time provider wired up, EVERY historical run must
    be labeled CURRENT_NIFTY200_HISTORICAL_SIMULATION, never claimed as an
    unbiased historical NIFTY 200 backtest (brief Section 60)."""
    from ema_scanner.universe.models import UNIVERSE_MODE_CURRENT_HISTORICAL_SIM, UNIVERSE_MODE_POINT_IN_TIME

    return UNIVERSE_MODE_POINT_IN_TIME if point_in_time_provider is not None else UNIVERSE_MODE_CURRENT_HISTORICAL_SIM
