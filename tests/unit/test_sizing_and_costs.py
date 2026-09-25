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
    assert result["reason"] == "invalid_stop_distance"


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
