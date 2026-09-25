"""Position sizing + cost tests (brief Section 93 #21-22)."""
from ema_scanner.config import CostsConfig
from ema_scanner.execution.costs import compute_transaction_cost_pct
from ema_scanner.execution.sizing import position_size


def test_position_size_basic_formula():
    result = position_size(capital=1_000_000, entry_price=100, stop_price=95, risk_per_trade_pct=0.5, lot_size=1)
    risk_capital = 1_000_000 * 0.005
    expected_qty = int(risk_capital / 5)
    assert result["qty"] == expected_qty
    assert result["reason"] == "ok"


def test_position_size_zero_when_stop_equals_entry():
    result = position_size(capital=1_000_000, entry_price=100, stop_price=100)
    assert result["qty"] == 0
    # A stop exactly AT entry has zero distance AND fails the strict LONG
    # geometry rule (stop must be < entry) -- Phase-2 Section 13 classifies
    # this as invalid_risk_geometry, checked before the distance math runs.
    assert result["reason"] == "invalid_risk_geometry"


def test_position_size_rejects_long_stop_above_entry():
    """Phase-2 Section 13 BLOCKER: a long stop placed ABOVE entry must never
    be silently accepted via abs(entry - stop) -- it's a structurally invalid
    setup, not just 'a very close stop'."""
    result = position_size(capital=1_000_000, entry_price=100, stop_price=105, direction="LONG")
    assert result["qty"] == 0
    assert result["reason"] == "invalid_risk_geometry"


def test_position_size_rejects_short_stop_below_entry():
    result = position_size(capital=1_000_000, entry_price=100, stop_price=95, direction="SHORT")
    assert result["qty"] == 0
    assert result["reason"] == "invalid_risk_geometry"


def test_position_size_accepts_valid_short_geometry():
    result = position_size(capital=1_000_000, entry_price=100, stop_price=105, direction="SHORT", risk_per_trade_pct=0.5)
    assert result["qty"] > 0
    assert result["reason"] == "ok"


def test_validate_risk_geometry_standalone():
    from ema_scanner.execution.sizing import validate_risk_geometry
    assert validate_risk_geometry(100, 95, "LONG") is True
    assert validate_risk_geometry(100, 105, "LONG") is False
    assert validate_risk_geometry(100, 105, "SHORT") is True
    assert validate_risk_geometry(100, 95, "SHORT") is False


def test_position_size_respects_lot_size():
    result = position_size(capital=100_000, entry_price=100, stop_price=99, risk_per_trade_pct=1.0, lot_size=25)
    assert result["qty"] % 25 == 0


def test_cost_scenarios_scale_monotonically():
    costs = CostsConfig()
    zero = compute_transaction_cost_pct(costs, "zero_cost")
    low = compute_transaction_cost_pct(costs, "low_cost")
    base = compute_transaction_cost_pct(costs, "base_cost")
    high = compute_transaction_cost_pct(costs, "high_cost")
    assert zero == 0.0
    assert zero < low < base < high


def test_cost_is_nonnegative():
    costs = CostsConfig()
    assert compute_transaction_cost_pct(costs, "base_cost") >= 0
