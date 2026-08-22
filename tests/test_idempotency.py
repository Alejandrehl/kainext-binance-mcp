from decimal import Decimal

from requests.exceptions import ConnectionError as ReqConnError

from kainext_binance_mcp.idempotency import derive_client_order_id, place_order_idempotent
from kainext_binance_mcp.models import CanonicalOrder


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


def test_requests_connection_error_triggers_query_before_retry_and_finds_order():
    """C1: place() lanza requests.exceptions.ConnectionError (TIPO REAL, no builtin).
    Debe hacer query-before-retry (get_order) y, si la orden EXISTE, devolverla sin re-place."""
    existing = {"orderId": 7, "status": "NEW"}
    calls = {"place": 0, "get": 0}

    def place():
        calls["place"] += 1
        raise ReqConnError("Connection aborted")  # tipo real de requests, no el builtin

    def get_order(symbol, cid):
        calls["get"] += 1
        return existing  # la orden SÍ se colocó pese a la caída de red

    out = place_order_idempotent(symbol="BTCUSDT", client_order_id="kbm_x",
                                 place=place, get_order=get_order)
    assert out is existing
    assert calls["place"] == 1 and calls["get"] == 1  # NO se re-coloca


def test_requests_connection_error_reraises_place_once_when_order_absent():
    """C1: tras requests.ConnectionError, si get_order devuelve None (-2013: no existe)
    → es seguro re-colocar EXACTAMENTE una vez con el mismo client_order_id."""
    ok = {"orderId": 9, "status": "FILLED"}
    seq = iter([ReqConnError("boom"), ok])  # primer place revienta, segundo OK
    calls = {"place": 0, "get": 0}

    def place():
        calls["place"] += 1
        nxt = next(seq)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def get_order(symbol, cid):
        calls["get"] += 1
        return None  # -2013 → confirmado que no existe

    out = place_order_idempotent(symbol="BTCUSDT", client_order_id="kbm_x",
                                 place=place, get_order=get_order)
    assert out is ok
    assert calls["place"] == 2 and calls["get"] == 1  # re-place una sola vez
