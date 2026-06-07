from decimal import Decimal
from unittest.mock import MagicMock
from kainext_binance_mcp.tools.read import get_balance, get_price, get_open_orders


def test_get_balance_filters_nonzero_and_uses_decimal():
    c = MagicMock()
    c.get_account.return_value = {"balances": [
        {"asset": "BTC", "free": "0.5", "locked": "0.0"},
        {"asset": "ETH", "free": "0", "locked": "0"},
    ]}
    out = get_balance(c)
    assert len(out) == 1 and out[0].asset == "BTC" and out[0].free == Decimal("0.5")


def test_get_price_decimal():
    c = MagicMock()
    c.get_symbol_ticker.return_value = {"symbol": "BTCUSDT", "price": "50000.10"}
    assert get_price(c, "BTCUSDT").price == Decimal("50000.10")


def test_get_open_orders_maps():
    c = MagicMock()
    c.get_open_orders.return_value = [{
        "symbol": "BTCUSDT", "orderId": 1, "clientOrderId": "x", "side": "BUY",
        "type": "LIMIT", "price": "50000", "origQty": "0.001", "executedQty": "0",
        "status": "NEW", "timeInForce": "GTC", "time": 123}]
    out = get_open_orders(c, "BTCUSDT")
    assert out[0].order_id == 1 and out[0].price == Decimal("50000")


def test_get_account_info_testnet_omits_key_perms():
    c = MagicMock()
    c.get_account.return_value = {"canTrade": True, "accountType": "SPOT",
                                  "commissionRates": {"maker": "0.001", "taker": "0.001"}}
    from kainext_binance_mcp.tools.read import get_account_info
    info = get_account_info(c, is_testnet=True)
    assert info.key_permissions is None and info.can_trade
