from decimal import Decimal

import pytest
from pydantic import ValidationError

from kainext_binance_mcp.models import CanonicalOrder


def test_limit_requires_price():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.001"), time_in_force="GTC", env="testnet")  # sin price

def test_market_rejects_price_and_tif():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0.001"), price=Decimal("50000"), env="testnet")

def test_xor_quantity_quote():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0.001"), quote_quantity=Decimal("50"), env="testnet")
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET", env="testnet")  # ninguno

def test_quote_only_market():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quote_quantity=Decimal("50"), price=Decimal("50000"),
                       time_in_force="GTC", env="testnet")

def test_valid_limit_ok():
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.001"), price=Decimal("50000"),
                       time_in_force="GTC", env="testnet")
    assert o.quantity == Decimal("0.001")

def test_rejects_non_positive():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0"), env="testnet")

def test_limit_requires_time_in_force():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.001"), price=Decimal("50000"),
                       env="testnet")  # sin time_in_force

def test_limit_requires_quantity():
    # LIMIT con price+tif pero sin quantity ni quote_quantity → línea "LIMIT requiere quantity"
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       price=Decimal("50000"), time_in_force="GTC", env="testnet")

def test_market_rejects_time_in_force_alone():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0.001"), time_in_force="GTC", env="testnet")


def test_cancel_result_status_constrained_and_status_round_trips():
    """B3: CancelResult según contrato §3.3 (order_id, status Literal, detail). El
    OrderStatus.result acepta CancelResult y lo distingue de OrderResult por su forma."""
    from kainext_binance_mcp.models import CancelResult, OrderResult, OrderStatus
    cr = CancelResult(order_id=7, status="CANCELED", detail="orden 7 CANCELED", env="testnet")
    assert cr.status == "CANCELED"
    with pytest.raises(ValidationError):
        CancelResult(order_id=7, status="WHATEVER", env="testnet")  # status fuera del Literal

    # Round-trip por dict (como hace ipc.serve → tools re-parsean): cancel → CancelResult.
    st_cancel = OrderStatus(intent_id="c1", state="executed", result=cr.model_dump(mode="json"))
    assert isinstance(st_cancel.result, CancelResult) and st_cancel.result.status == "CANCELED"

    # Y un payload de orden sigue resolviendo a OrderResult (no se confunde la union).
    orr = OrderResult(order_id=9, client_order_id="kbm_x", status="FILLED",
                      executed_qty=Decimal("0.0002"), cummulative_quote_qty=Decimal("10"),
                      env="testnet")
    st_order = OrderStatus(intent_id="i1", state="executed", result=orr.model_dump(mode="json"))
    assert isinstance(st_order.result, OrderResult) and st_order.result.status == "FILLED"


def test_canonical_order_symbol_pattern():
    """Trust boundary: symbol inválido no puede ni construirse (nunca llega a AppleScript)."""
    from decimal import Decimal

    import pytest
    from pydantic import ValidationError

    from kainext_binance_mcp.models import CanonicalOrder
    ok = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                        quote_quantity=Decimal("10"), env="testnet")
    assert ok.symbol == "BTCUSDT"
    for bad in ('BTC"USDT', "btcusdt", "BTC USDT", "B", "X" * 21, 'A\\"; do shell script "x"'):
        with pytest.raises(ValidationError):
            CanonicalOrder(symbol=bad, side="BUY", type="MARKET",
                           quote_quantity=Decimal("10"), env="testnet")
