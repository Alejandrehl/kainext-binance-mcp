from decimal import Decimal
import pytest
from kainext_binance_mcp.models import CanonicalOrder, OrderResult
from kainext_binance_mcp.intents import IntentStore, IntentStateError

def _order():
    return CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                          quote_quantity=Decimal("10"), env="testnet")

def test_register_returns_unique_uuid_pending():
    s = IntentStore(ttl_seconds=300, now=lambda: 1000)
    i1 = s.register(_order()); i2 = s.register(_order())
    assert i1 != i2
    assert s.get(i1).state == "pending"

def test_approve_then_execute_terminal():
    s = IntentStore(ttl_seconds=300, now=lambda: 1000)
    iid = s.register(_order())
    s.mark_approved(iid)
    res = OrderResult(order_id=1, client_order_id="kbm_x", status="FILLED",
                      executed_qty=Decimal("0.0002"), cummulative_quote_qty=Decimal("10"), env="testnet")
    s.mark_executed(iid, res)
    assert s.get(iid).state == "executed"
    with pytest.raises(IntentStateError):  # one-shot: no re-ejecutar
        s.mark_executed(iid, res)

def test_expired():
    t = {"v": 1000}
    s = IntentStore(ttl_seconds=60, now=lambda: t["v"])
    iid = s.register(_order())
    t["v"] = 1100  # +100s > ttl
    assert s.get(iid).state == "expired"

def test_reject_is_terminal():
    s = IntentStore(ttl_seconds=300, now=lambda: 1000)
    iid = s.register(_order()); s.mark_rejected(iid)
    assert s.get(iid).state == "rejected"
    with pytest.raises(IntentStateError):
        s.mark_approved(iid)


def test_register_cancel_creates_pending_cancel_intent():
    s = IntentStore(ttl_seconds=300, now=lambda: 1000)
    iid = s.register_cancel("BTCUSDT", 42)
    it = s.get(iid)
    assert it.state == "pending" and it.kind == "cancel"
    assert it.order is None and it.cancel_symbol == "BTCUSDT" and it.cancel_order_id == 42


def test_pending_count_counts_only_live_pending():
    t = {"v": 1000}
    s = IntentStore(ttl_seconds=60, now=lambda: t["v"])
    a = s.register(_order()); s.register(_order())
    assert s.pending_count() == 2
    s.mark_rejected(a)
    assert s.pending_count() == 1
    t["v"] = 2000  # todo expira
    assert s.pending_count() == 0
