"""Position sizing (notebook Cell 34; audit row 27; Phase-2 Section 13 --
BLOCKER: invalid stop/entry geometry must hard-fail, not hide behind abs()).

Kept FULLY SEPARATE from signal generation (brief Section 44): this module
never changes what counts as a signal, only how many shares a given signal
would be sized to -- and now, whether the trade's risk geometry is even valid
at all.
"""
from __future__ import annotations

import math
from typing import Literal


def position_size(
    capital: float, entry_price: float, stop_price: float,
    risk_per_trade_pct: float = 0.5, lot_size: int = 1, min_qty: int = 1, max_qty: int | None = None,
    direction: Literal["LONG", "SHORT"] = "LONG",
) -> dict:
    """**Bug fixed (Phase-2 Section 13):** v1 computed `abs(entry - stop)`,
    which silently accepts a structurally invalid stop (e.g. a "long" stop
    placed ABOVE entry) as if it were just a very close stop. Geometry is now
    validated explicitly before any distance/quantity math:

        LONG:  stop must be <  entry
        SHORT: stop must be >  entry

    An invalid geometry returns `qty=0, reason="invalid_risk_geometry"` --
    never a trade.
    """
    if direction == "LONG" and not (stop_price < entry_price):
        return {"qty": 0, "risk_capital": 0.0, "reason": "invalid_risk_geometry"}
    if direction == "SHORT" and not (stop_price > entry_price):
        return {"qty": 0, "risk_capital": 0.0, "reason": "invalid_risk_geometry"}

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


def validate_risk_geometry(entry_price: float, stop_price: float, direction: Literal["LONG", "SHORT"] = "LONG") -> bool:
    """Standalone geometry check, usable at signal-construction time (before
    sizing is even attempted) so an INVALID_RISK_GEOMETRY signal can be
    flagged in the scanner output too, not only inside the backtest engine."""
    if direction == "LONG":
        return stop_price < entry_price
    return stop_price > entry_price
