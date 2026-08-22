import json
from decimal import Decimal
from unittest.mock import MagicMock

from binance.client import Client
from binance.exceptions import BinanceAPIException

from kainext_binance_mcp.models import CanonicalOrder
from kainext_binance_mcp_confirmer.executor import handle_cancel_intent, handle_intent


def _order():
    return CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                          quote_quantity=Decimal("10"), env="testnet")

def test_does_not_execute_when_cancelled():
    client = MagicMock(); store = MagicMock()
    handle_intent(order=_order(), intent_id="i1", store=store, client=client,
                  estimator=MagicMock(), confirm=lambda text: False, nonce="n")
    client.create_order.assert_not_called()
    store.mark_rejected.assert_called_once_with("i1")

def test_executes_with_derived_id_when_confirmed():
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    client.create_order.return_value = {"orderId": 9, "clientOrderId": "kbm_x",
        "status": "FILLED", "executedQty": "0.0002", "cummulativeQuoteQty": "10", "fills": []}
    handle_intent(order=_order(), intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    assert client.create_order.called
    # el clientOrderId pasado lo derivó el confirmador (kbm_...)
    assert client.create_order.call_args.kwargs["newClientOrderId"].startswith("kbm_")
    store.mark_executed.assert_called_once()


def test_cancel_does_not_cancel_without_confirm():
    client = MagicMock(); store = MagicMock()
    client.get_order.return_value = {"status": "NEW"}
    handle_cancel_intent(symbol="BTCUSDT", order_id=1, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: False)
    client.cancel_order.assert_not_called()
    store.mark_rejected.assert_called_once_with("c1")


def test_cancel_cancels_after_confirm_with_toctou_recheck():
    client = MagicMock(); store = MagicMock()
    client.get_order.return_value = {"status": "NEW"}  # re-consulta justo antes (TOCTOU)
    client.cancel_order.return_value = {"orderId": 1, "origClientOrderId": "kbm_x",
                                        "status": "CANCELED", "executedQty": "0",
                                        "cummulativeQuoteQty": "0"}
    handle_cancel_intent(symbol="BTCUSDT", order_id=1, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True)
    client.get_order.assert_called_once()
    client.cancel_order.assert_called_once()
    store.mark_executed.assert_called_once()


def test_cancel_skips_if_no_longer_cancelable():
    client = MagicMock(); store = MagicMock()
    client.get_order.return_value = {"status": "FILLED"}
    handle_cancel_intent(symbol="BTCUSDT", order_id=1, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True)
    client.cancel_order.assert_not_called()
    store.mark_failed.assert_called_once()


def _limit_order():
    return CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                          quantity=Decimal("0.001"), price=Decimal("100"),
                          time_in_force="GTC", env="testnet")


def test_infeasible_preview_marks_failed_without_dialog():
    """preview.feasible=False → mark_failed con la razón; nunca pide confirmación ni ejecuta."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=False, reason="notional < mínimo")
    confirm = MagicMock()
    handle_intent(order=_order(), intent_id="i1", store=store, client=client,
                  estimator=est, confirm=confirm, nonce="n")
    confirm.assert_not_called()
    client.create_order.assert_not_called()
    store.mark_failed.assert_called_once()
    assert store.mark_failed.call_args.args[1].message == "notional < mínimo"


def test_execute_failure_is_sanitized_to_mark_failed():
    """Si create_order revienta, se mapea a ToolError y mark_failed (no se filtra el raw)."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    boom = Exception("network down"); boom.code = -1001
    client.create_order.side_effect = boom
    handle_intent(order=_order(), intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    store.mark_executed.assert_not_called()
    store.mark_failed.assert_called_once()
    assert store.mark_failed.call_args.args[1].code == -1001


def test_create_limit_sends_price_tif_and_quantity():
    """Rama LIMIT de _create: manda timeInForce/price/quantity (no quoteOrderQty)."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.001"),
                                          price=Decimal("100"))
    client.create_order.return_value = {"orderId": 1, "clientOrderId": "kbm_x",
        "status": "NEW", "executedQty": "0", "cummulativeQuoteQty": "0", "fills": []}
    handle_intent(order=_limit_order(), intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    kw = client.create_order.call_args.kwargs
    assert kw["timeInForce"] == "GTC" and kw["price"] == "100" and kw["quantity"] == "0.001"
    assert "quoteOrderQty" not in kw


def test_create_market_with_quantity_sends_quantity_not_quote():
    """Rama MARKET con quantity (no quote_quantity): manda quantity efectiva."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    client.create_order.return_value = {"orderId": 1, "clientOrderId": "kbm_x",
        "status": "FILLED", "executedQty": "0.0002", "cummulativeQuoteQty": "10", "fills": []}
    order = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                           quantity=Decimal("0.0002"), env="testnet")
    handle_intent(order=order, intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    kw = client.create_order.call_args.kwargs
    assert kw["quantity"] == "0.0002" and "quoteOrderQty" not in kw


def test_idempotency_recovers_existing_order_on_timeout():
    """place() da TimeoutError; _get_order encuentra la orden → se usa esa (no se reintenta a ciegas)."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    existing = {"orderId": 7, "clientOrderId": "kbm_x", "status": "FILLED",
                "executedQty": "0.0002", "cummulativeQuoteQty": "10", "fills": []}
    client.create_order.side_effect = TimeoutError("timeout")
    client.get_order.return_value = existing  # _get_order la recupera por origClientOrderId
    handle_intent(order=_order(), intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    store.mark_executed.assert_called_once()
    assert store.mark_executed.call_args.args[1].order_id == 7


def test_get_order_returns_none_when_lookup_raises():
    """En timeout, si get_order revienta (-2013 simulado como excepción) → _get_order None
    → place() se reintenta; con el segundo place exitoso se ejecuta."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    ok = {"orderId": 9, "clientOrderId": "kbm_x", "status": "FILLED",
          "executedQty": "0.0002", "cummulativeQuoteQty": "10", "fills": []}
    client.create_order.side_effect = [TimeoutError("timeout"), ok]
    client.get_order.side_effect = Exception("-2013 order does not exist")  # _get_order → None
    handle_intent(order=_order(), intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    assert client.create_order.call_count == 2
    store.mark_executed.assert_called_once()


def test_cancel_get_order_failure_is_sanitized():
    """Si la re-consulta (get_order) revienta antes de cancelar → mark_failed, nunca cancela."""
    client = MagicMock(); store = MagicMock()
    boom = Exception("api error"); boom.code = -1001
    client.get_order.side_effect = boom
    handle_cancel_intent(symbol="BTCUSDT", order_id=1, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True)
    client.cancel_order.assert_not_called()
    store.mark_failed.assert_called_once()
    assert store.mark_failed.call_args.args[1].code == -1001


class _Resp:
    """Stub mínimo de requests.Response para construir un BinanceAPIException REAL."""
    def __init__(self, text):
        self.text = text
        self.request = None


def test_execute_failure_scrubs_api_key_from_tool_error():
    """C2: create_order revienta con un BinanceAPIException (tipo REAL) cuyo mensaje
    contiene la API key del client. El ToolError de mark_failed debe salir REDACTED.
    Usa un Client REAL de python-binance (API_KEY/API_SECRET de verdad)."""
    api_key = "LEAKED_API_KEY_abc123XYZ"
    client = Client(api_key, "LEAKED_API_SECRET_def456", ping=False)
    store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    leaked = json.dumps({"code": -1022,
                         "msg": f"signature for key {api_key} invalid"})
    boom = BinanceAPIException(_Resp(leaked), 400, leaked)  # tipo real; .code=-1022, .message con la key
    client.create_order = MagicMock(side_effect=boom)
    handle_intent(order=_order(), intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    store.mark_executed.assert_not_called()
    store.mark_failed.assert_called_once()
    err = store.mark_failed.call_args.args[1]
    assert api_key not in err.message, "la API key NO debe filtrarse al modelo"
    assert "REDACTED" in err.message
    assert err.code == -1022


def test_env_mismatch_marks_failed_without_dialog_or_execute():
    """C3: intent env='testnet' contra confirmador env='mainnet' → mark_failed; NO se estima,
    NO se muestra diálogo, NO se ejecuta. Usa un CanonicalOrder REAL (env del wire)."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    confirm = MagicMock()
    order = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                           quote_quantity=Decimal("10"), env="testnet")  # tipo real
    handle_intent(order=order, intent_id="i1", store=store, client=client,
                  estimator=est, confirm=confirm, nonce="n", confirmer_env="mainnet")
    est.estimate.assert_not_called()
    confirm.assert_not_called()
    client.create_order.assert_not_called()
    store.mark_executed.assert_not_called()
    store.mark_failed.assert_called_once()
    assert store.mark_failed.call_args.args[1].code == "env_mismatch"


def test_cancel_env_mismatch_marks_failed_without_query_or_cancel():
    """C3 (cancel): env del intent ≠ env del confirmador → mark_failed; ni get_order ni cancel."""
    client = MagicMock(); store = MagicMock()
    handle_cancel_intent(symbol="BTCUSDT", order_id=1, env="mainnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True,
                         confirmer_env="testnet")
    client.get_order.assert_not_called()
    client.cancel_order.assert_not_called()
    store.mark_failed.assert_called_once()
    assert store.mark_failed.call_args.args[1].code == "env_mismatch"


def test_cancel_failure_after_confirm_is_sanitized():
    """get_order OK + confirm True, pero cancel_order revienta → mark_failed sanitizado."""
    client = MagicMock(); store = MagicMock()
    client.get_order.return_value = {"status": "NEW"}
    boom = Exception("cancel rejected"); boom.code = -2011
    client.cancel_order.side_effect = boom
    handle_cancel_intent(symbol="BTCUSDT", order_id=1, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True)
    store.mark_executed.assert_not_called()
    store.mark_failed.assert_called_once()
    assert store.mark_failed.call_args.args[1].code == -2011


def test_estimate_failure_marks_failed_not_pending():
    """Si la re-estimación autoritativa falla (red/símbolo), el intent queda FAILED al tiro
    — antes la excepción mataba el hilo y el intent quedaba pending hasta el TTL (300s)."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.side_effect = RuntimeError("network down")
    handle_intent(order=_order(), intent_id="i9", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    client.create_order.assert_not_called()
    store.mark_failed.assert_called_once()
    assert store.mark_failed.call_args.args[0] == "i9"
