from decimal import Decimal
from kainext_binance_mcp.market import round_to_step, round_to_tick, validate_notional

def test_round_qty_floor_to_step():
    assert round_to_step(Decimal("0.123456"), Decimal("0.00001")) == Decimal("0.12345")

def test_round_price_to_tick():
    assert round_to_tick(Decimal("50000.017"), Decimal("0.01")) == Decimal("50000.01")

def test_step_zero_is_noop():
    assert round_to_step(Decimal("1.23"), Decimal("0")) == Decimal("1.23")

def test_notional_ok_and_fail():
    assert validate_notional(Decimal("0.001"), Decimal("50000"), Decimal("5")) is None
    assert "notional" in validate_notional(Decimal("0.00001"), Decimal("50000"), Decimal("5")).lower()
