from unittest.mock import patch

import pytest

from kainext_binance_mcp.guard import GuardError


def test_server_bootstrap_aborts_if_read_key_has_trade(monkeypatch):
    env = {"BINANCE_ENV": "mainnet", "BINANCE_READ_API_KEY": "k", "BINANCE_READ_API_SECRET": "s"}
    with patch("kainext_binance_mcp.runtime.make_client") as mc:
        client = mc.return_value
        client.get_account_api_permissions.return_value = {
            "enableSpotAndMarginTrading": True, "enableWithdrawals": False,
            "permitsUniversalTransfer": False, "enableInternalTransfer": False,
            "enableMargin": False, "enableFutures": False,
            "enablePortfolioMarginTrading": False, "ipRestrict": True}
        from kainext_binance_mcp.server import bootstrap
        with pytest.raises(GuardError):
            bootstrap(env)
