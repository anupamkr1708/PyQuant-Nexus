"""Research data-completeness audit (Phase-3 BLOCKER 27).

**Bug fixed:** research commands (event-study, backtest, walk-forward,
sensitivity) silently skipped any symbol that failed to fetch/build features
(a bare `except DataUnavailableError: continue` in `_load_universe_frames`)
-- an economic result could be reported without ever disclosing how many of
the REQUESTED constituents were actually evaluated. This module produces an
explicit audit report alongside every research run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ResearchDataAuditEntry:
    symbol: str
    status: str  # "ELIGIBLE" | "EXCLUDED"
    reason: str | None
    rows: int
    data_source: str | None
    missing_sessions: int
    coverage_start: str | None
    coverage_end: str | None


@dataclass
class ResearchDataAuditReport:
    requested_symbols: int
    eligible_symbols: int
    excluded_symbols: int
    entries: list[ResearchDataAuditEntry] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([vars(e) for e in self.entries])

    def summary_line(self) -> str:
        return (
            f"Requested {self.requested_symbols} constituent(s); "
            f"{self.eligible_symbols} eligible / {self.excluded_symbols} excluded. "
            f"Any economic result below reflects ONLY the eligible subset."
        )


def build_research_data_audit(
    requested_symbols: list[str], eligible_frames: dict[str, pd.DataFrame],
    exclusions: dict[str, str], resolved_sources: dict[str, str] | None = None,
    missing_sessions: dict[str, int] | None = None,
) -> ResearchDataAuditReport:
    resolved_sources = resolved_sources or {}
    missing_sessions = missing_sessions or {}
    entries = []
    for sym in requested_symbols:
        if sym in eligible_frames:
            feats = eligible_frames[sym]
            entries.append(ResearchDataAuditEntry(
                symbol=sym, status="ELIGIBLE", reason=None, rows=len(feats),
                data_source=resolved_sources.get(sym), missing_sessions=missing_sessions.get(sym, 0),
                coverage_start=str(feats.index.min().date()) if len(feats) else None,
                coverage_end=str(feats.index.max().date()) if len(feats) else None,
            ))
        else:
            entries.append(ResearchDataAuditEntry(
                symbol=sym, status="EXCLUDED", reason=exclusions.get(sym, "unknown"), rows=0,
                data_source=resolved_sources.get(sym), missing_sessions=missing_sessions.get(sym, 0),
                coverage_start=None, coverage_end=None,
            ))
    return ResearchDataAuditReport(
        requested_symbols=len(requested_symbols), eligible_symbols=len(eligible_frames),
        excluded_symbols=len(requested_symbols) - len(eligible_frames), entries=entries,
    )
