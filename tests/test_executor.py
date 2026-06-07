from decimal import Decimal
from unittest.mock import MagicMock
from kainext_binance_mcp.models import CanonicalOrder
from kainext_binance_mcp_confirmer.executor import handle_intent, handle_cancel_intent

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
