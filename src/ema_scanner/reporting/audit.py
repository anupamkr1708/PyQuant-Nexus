"""Runtime self-audit helper (brief Section 104 checklist), used by the CLI's
`show-config` and end-of-run summary to surface anything that looks off before
a person trusts the output."""
from __future__ import annotations

from ema_scanner.config import Config


def audit_config(cfg: Config) -> list[str]:
    warnings = []
    if cfg.data.primary_provider == "NSE":
        warnings.append(
            "primary_provider=NSE, but data/nse.py's endpoint is UNVERIFIED in this build "
            "(see DATA_SOURCES.md) — confirm it before relying on this for a live scan."
        )
    if cfg.costs.brokerage_pct or cfg.costs.stt_pct:
        warnings.append("Transaction costs are PLACEHOLDER_UNVERIFIED values copied from the source notebook (brief Section 45) — confirm against your actual broker/current tax rates.")
    return warnings
