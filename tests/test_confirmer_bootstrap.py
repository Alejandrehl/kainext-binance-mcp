"""Bootstrap del confirmador (§4.2b): test-call firmado + guard de la trade key en mainnet."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kainext_binance_mcp.guard import GuardError
from kainext_binance_mcp_confirmer import __main__ as confirmer


def _perms(*, withdrawals=False, futures=False, universal=False):
    return {
        "enableSpotAndMarginTrading": True, "enableWithdrawals": withdrawals,
        "permitsUniversalTransfer": universal, "enableInternalTransfer": False,
        "enableMargin": False, "enableFutures": futures,
        "enablePortfolioMarginTrading": False, "ipRestrict": True}


def test_confirmer_bootstrap_ok_on_testnet_skips_guard():
    env = {"BINANCE_ENV": "testnet", "BINANCE_TRADE_API_KEY": "k",
           "BINANCE_TRADE_API_SECRET": "s"}
    with patch("kainext_binance_mcp.runtime.make_client") as mc:
        client = mc.return_value
        client.get_account.return_value = {"canTrade": True}
        settings, _ = confirmer.bootstrap(env)
        assert settings.is_testnet
        client.get_account.assert_called_once()  # test-call firmado
        client.get_account_api_permissions.assert_not_called()  # no guard en testnet


def test_confirmer_bootstrap_aborts_if_trade_key_can_withdraw():
    env = {"BINANCE_ENV": "mainnet", "BINANCE_TRADE_API_KEY": "k",
           "BINANCE_TRADE_API_SECRET": "s"}
    with patch("kainext_binance_mcp.runtime.make_client") as mc:
        client = mc.return_value
        client.get_account_api_permissions.return_value = _perms(withdrawals=True)
        with pytest.raises(GuardError):
            confirmer.bootstrap(env)


def test_confirmer_make_estimator_uses_client():
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
    client.get_symbol_ticker.return_value = {"price": "50000"}
    est = confirmer._make_estimator(client)
    order = MagicMock(symbol="BTCUSDT", type="MARKET", price=None,
                      quote_quantity=Decimal("100"), quantity=None, env="mainnet")
    preview = est.estimate(order)
    assert preview.env == "mainnet"
