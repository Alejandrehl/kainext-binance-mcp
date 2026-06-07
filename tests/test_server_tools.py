"""Cobertura del wiring de tools del MCP server (_register_tools + _make_estimator).

Cada @mcp.tool() delega en funciones ya testeadas; acá verificamos que el cableado
(qué dependencia recibe cada tool, con qué args) es correcto, invocando la función
subyacente (`.fn`) que FastMCP registró. El server NUNCA ejecuta: las write delegan
en el confirmador vía ipc."""
from __future__ import annotations
from decimal import Decimal
from unittest.mock import MagicMock

from kainext_binance_mcp import server as srv


def _register(client, ipc, market, *, is_testnet=True):
    # Aísla el registro en una FastMCP nueva por test (no contamina el módulo global).
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("test")
    srv.mcp = mcp
    srv._register_tools(client, ipc, market, is_testnet=is_testnet)
    return mcp._tool_manager


def _fn(tm, name):
    return tm.get_tool(name).fn


def test_make_estimator_closures_call_client():
    client = MagicMock()
    client.get_symbol_info.return_value = {
        "symbol": "BTCUSDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
            {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.0001"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ],
    }
    client.get_symbol_ticker.return_value = {"price": "50000.0"}
    est = srv._make_estimator(client)
    order = MagicMock(symbol="BTCUSDT", type="MARKET", price=None,
                      quote_quantity=Decimal("100"), quantity=None, env="testnet")
    preview = est.estimate(order)  # ejercita get_filters + get_price
    assert preview.env == "testnet"
    client.get_symbol_info.assert_called_with("BTCUSDT")
    client.get_symbol_ticker.assert_called_with(symbol="BTCUSDT")


def test_read_tools_delegate_to_client():
    client = MagicMock()
    client.get_account.return_value = {
        "balances": [{"asset": "BTC", "free": "1", "locked": "0"}],
        "canTrade": True, "commissionRates": {}, "accountType": "SPOT"}
    client.get_symbol_ticker.return_value = {"symbol": "BTCUSDT", "price": "50000"}
    client.get_open_orders.return_value = []
    client.get_all_orders.return_value = []
    tm = _register(client, MagicMock(), MagicMock(), is_testnet=True)

    assert _fn(tm, "binance_get_balance")()[0].asset == "BTC"
    assert _fn(tm, "binance_get_price")("BTCUSDT").price == Decimal("50000")
    assert _fn(tm, "binance_get_open_orders")() == []
    assert _fn(tm, "binance_get_order_history")("BTCUSDT") == []
    assert _fn(tm, "binance_get_account_info")().can_trade is True


def test_write_tools_delegate_to_ipc_and_never_execute():
    client = MagicMock()
    ipc = MagicMock()
    ipc.register.return_value = ("iid-1", 123)
    ipc.register_cancel.return_value = ("iid-2", 456)
    ipc.status.return_value = {"intent_id": "iid-1", "state": "pending",
                               "result": None, "error": None}
    client.get_order.return_value = {"status": "NEW"}
    from kainext_binance_mcp.models import OrderPreview
    market = MagicMock()
    market.estimate.return_value = OrderPreview(
        effective_qty=Decimal("0.0002"), price=None, est_notional=Decimal("10"),
        est_commission=Decimal("0.01"), env="testnet", feasible=True)
    tm = _register(client, ipc, market, is_testnet=True)

    prop = _fn(tm, "binance_spot_order_propose")(
        symbol="BTCUSDT", side="BUY", type="MARKET", env="testnet",
        quote_quantity=Decimal("10"))
    assert prop.intent_id == "iid-1"
    ipc.register.assert_called_once()
    client.create_order.assert_not_called()  # el server NUNCA ejecuta

    st = _fn(tm, "binance_spot_order_status")("iid-1")
    assert st.state == "pending"

    cprop = _fn(tm, "binance_cancel_order_propose")(symbol="BTCUSDT", order_id=7, env="testnet")
    assert cprop.intent_id == "iid-2"
    ipc.register_cancel.assert_called_once()

    cst = _fn(tm, "binance_cancel_order_status")("iid-1")
    assert cst.state == "pending"
