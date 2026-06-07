from decimal import Decimal
from kainext_binance_mcp.models import CanonicalOrder
from kainext_binance_mcp.idempotency import derive_client_order_id

def _order():
    return CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                          quantity=Decimal("0.001"), price=Decimal("50000"),
                          time_in_force="GTC", env="testnet")

def test_id_is_deterministic_for_same_inputs():
    o = _order()
    assert derive_client_order_id(o, "intent-1", "nonceX") == derive_client_order_id(o, "intent-1", "nonceX")

def test_id_changes_with_intent_or_nonce():
    o = _order()
    assert derive_client_order_id(o, "intent-1", "n") != derive_client_order_id(o, "intent-2", "n")
    assert derive_client_order_id(o, "intent-1", "n1") != derive_client_order_id(o, "intent-1", "n2")

def test_id_format_binance_valid():
    cid = derive_client_order_id(_order(), "intent-1", "n")
    assert cid.startswith("kbm_") and len(cid) <= 36 and cid.replace("kbm_", "").isalnum()
