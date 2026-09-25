"""Universe record types (brief Section 23)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseConstituent:
    symbol: str
    company_name: str | None
    sector: str | None
    provider_ticker: str
    effective_date: str | None


UNIVERSE_MODE_POINT_IN_TIME = "POINT_IN_TIME_NIFTY200"
UNIVERSE_MODE_CURRENT_HISTORICAL_SIM = "CURRENT_NIFTY200_HISTORICAL_SIMULATION"
UNIVERSE_MODE_CUSTOM = "CUSTOM_UNIVERSE"
