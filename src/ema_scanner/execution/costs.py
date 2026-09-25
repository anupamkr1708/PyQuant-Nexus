"""Transaction cost model (notebook Cell 34; audit row 27, and docs/NOTEBOOK_AUDIT.md §2 pt 3).

category: PLACEHOLDER_UNVERIFIED. These values are copied unchanged from the
notebook's own Config. The refactor brief (Section 45) explicitly forbids
treating them as verified current broker/tax figures without checking an
authoritative source — this was NOT done as part of this refactor (no network
access to a broker fee schedule / SEBI circular in this environment; see
RESEARCH_LIMITATIONS.md). Confirm against your actual broker and current
STT/GST/SEBI/stamp-duty rates before trusting any net-of-cost number.
"""
from __future__ import annotations

from dataclasses import dataclass

from ema_scanner.config import CostsConfig


@dataclass(frozen=True)
class CostScenario:
    name: str
    multiplier: float  # applied to every percentage cost component


COST_SCENARIOS = {
    "zero_cost": CostScenario("zero_cost", 0.0),
    "low_cost": CostScenario("low_cost", 0.5),
    "base_cost": CostScenario("base_cost", 1.0),
    "high_cost": CostScenario("high_cost", 2.0),
}


def compute_transaction_cost_pct(costs: CostsConfig, scenario: str = "base_cost") -> float:
    """One-leg cost fraction (e.g. 0.0018 == 0.18%). Multiply by 2 for round-trip."""
    mult = COST_SCENARIOS[scenario].multiplier
    taxable = costs.brokerage_pct + costs.exchange_charges_pct
    gst = taxable * costs.gst_pct
    total_pct = (
        costs.brokerage_pct + costs.stt_pct + costs.exchange_charges_pct + gst
        + costs.stamp_duty_pct + costs.sebi_charges_pct + costs.slippage_pct
    )
    return (total_pct / 100.0) * mult
