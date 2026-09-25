"""Transaction cost model (notebook Cell 34; audit row 27; Phase-2 Section 17).

category: PLACEHOLDER_UNVERIFIED. These values are copied unchanged from the
notebook's own Config. The refactor brief (Section 45) explicitly forbids
treating them as verified current broker/tax figures without checking an
authoritative source -- this was NOT done as part of this refactor (no
network access to a broker fee schedule / SEBI circular in this environment;
see RESEARCH_LIMITATIONS.md). Confirm against your actual broker and current
STT/GST/SEBI/stamp-duty rates before trusting any net-of-cost number.

**Phase-2 change:** costs are now SIDE-AWARE (buy vs sell), because Indian
delivery-equity STT and stamp duty have historically applied asymmetrically
by side. `compute_transaction_cost_pct(side=...)` returns the correct leg's
cost. A full per-broker / per-product-type (delivery vs intraday) model is
explicitly NOT_IMPLEMENTED -- deliberately out of scope here to avoid building
a detailed cost hierarchy on top of unverified numbers (see configs/default.yaml).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ema_scanner.config import CostsConfig

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class CostScenario:
    name: str
    multiplier: float  # applied to every percentage cost component


COST_SCENARIOS = {
    "zero_cost": CostScenario("zero_cost", 0.0),
    "low_cost": CostScenario("low_cost", 0.5),
    "base_cost": CostScenario("base_cost", 1.0),
    "high_cost": CostScenario("high_cost", 2.0),
    "stress_cost": CostScenario("stress_cost", 3.0),
}


def compute_transaction_cost_pct(costs: CostsConfig, scenario: str = "base_cost", side: Side = "buy") -> float:
    """One-leg cost fraction for the given SIDE (e.g. 0.0018 == 0.18%).
    Round-trip cost is `compute_transaction_cost_pct(..., side="buy") +
    compute_transaction_cost_pct(..., side="sell")`, NOT `2 * one_side`,
    because the two sides are no longer assumed symmetric."""
    mult = COST_SCENARIOS[scenario].multiplier
    stt = (costs.stt_buy_pct if side == "buy" else costs.stt_sell_pct)
    if stt is None:
        stt = costs.stt_pct
    stamp_duty = costs.stamp_duty_pct if (side == "buy" or not costs.stamp_duty_buy_only) else 0.0

    taxable = costs.brokerage_pct + costs.exchange_charges_pct
    gst = taxable * costs.gst_pct
    total_pct = (
        costs.brokerage_pct + stt + costs.exchange_charges_pct + gst
        + stamp_duty + costs.sebi_charges_pct + costs.slippage_pct
    )
    return (total_pct / 100.0) * mult


def compute_round_trip_cost_pct(costs: CostsConfig, scenario: str = "base_cost") -> float:
    """Sum of the buy-leg and sell-leg costs -- replaces the old
    `2 * one_leg_cost_pct` assumption wherever a round-trip figure is needed."""
    return (
        compute_transaction_cost_pct(costs, scenario, side="buy")
        + compute_transaction_cost_pct(costs, scenario, side="sell")
    )
