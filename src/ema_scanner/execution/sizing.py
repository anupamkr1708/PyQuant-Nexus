"""Position sizing (notebook Cell 34; audit row 27).

Kept FULLY SEPARATE from signal generation (brief Section 44): this module never
changes what counts as a signal, only how many shares a given signal would be
sized to.
"""
from __future__ import annotations

import math


def position_size(
    capital: float, entry_price: float, stop_price: float,
    risk_per_trade_pct: float = 0.5, lot_size: int = 1, min_qty: int = 1, max_qty: int | None = None,
) -> dict:
    risk_capital = capital * (risk_per_trade_pct / 100.0)
    per_share_risk = abs(entry_price - stop_price)
    if per_share_risk <= 0 or math.isnan(per_share_risk):
        return {"qty": 0, "risk_capital": risk_capital, "reason": "invalid_stop_distance"}
    lots = max(int((risk_capital / per_share_risk) // lot_size), 0)
    qty = max(lots * lot_size, 0)
    if qty < min_qty:
        return {"qty": 0, "risk_capital": risk_capital, "reason": "below_min_qty"}
    if max_qty is not None:
        qty = min(qty, max_qty)
    return {"qty": qty, "risk_capital": risk_capital, "per_share_risk": per_share_risk, "reason": "ok"}
