"""Symbol / identifier mapping layer (brief Section 25).

Minimal implementation: an in-memory mapping table keyed by a stable internal
ID, with symbol-history entries. No real historical rename dataset is wired up
(same honesty policy as universe/historical.py) — this is scaffolding for one
to be added later.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SecurityMaster:
    _by_internal_id: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)  # id -> [(symbol, from, to)]

    def register(self, internal_id: str, symbol: str, effective_from: str, effective_to: str = "9999-12-31") -> None:
        self._by_internal_id.setdefault(internal_id, []).append((symbol, effective_from, effective_to))

    def symbol_as_of(self, internal_id: str, as_of_date: str) -> str | None:
        for symbol, start, end in self._by_internal_id.get(internal_id, []):
            if start <= as_of_date <= end:
                return symbol
        return None
