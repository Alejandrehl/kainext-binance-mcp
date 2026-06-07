import pytest
from kainext_binance_mcp.models import KeyPermissions
from kainext_binance_mcp.guard import assert_trade_key_safe, assert_read_key_safe, GuardError, perms_from_api

SAFE_TRADE = dict(enable_spot_and_margin_trading=True, enable_withdrawals=False,
                  permits_universal_transfer=False, enable_internal_transfer=False,
                  enable_margin=False, enable_futures=False,
                  enable_portfolio_margin_trading=False, ip_restrict=True)

def test_trade_key_safe_passes():
    assert_trade_key_safe(KeyPermissions(**SAFE_TRADE))  # no raise

def test_trade_key_without_spot_trading_aborts():
    with pytest.raises(GuardError):
        assert_trade_key_safe(KeyPermissions(**{**SAFE_TRADE, "enable_spot_and_margin_trading": False}))

@pytest.mark.parametrize("flag", ["enable_withdrawals", "permits_universal_transfer",
                                  "enable_internal_transfer", "enable_futures",
                                  "enable_portfolio_margin_trading"])
def test_trade_key_overpermissioned_aborts(flag):
    with pytest.raises(GuardError):
        assert_trade_key_safe(KeyPermissions(**{**SAFE_TRADE, flag: True}))

def test_trade_key_without_ip_restrict_aborts():
    with pytest.raises(GuardError):
        assert_trade_key_safe(KeyPermissions(**{**SAFE_TRADE, "ip_restrict": False}))

def test_read_key_with_trading_aborts():
    with pytest.raises(GuardError):
        assert_read_key_safe(KeyPermissions(**{**SAFE_TRADE, "enable_spot_and_margin_trading": True}))

def test_read_key_clean_passes():
    perms = {**SAFE_TRADE, "enable_spot_and_margin_trading": False, "ip_restrict": False}
    assert_read_key_safe(KeyPermissions(**perms))  # read key no exige ip_restrict

def test_perms_from_api_maps_camelcase():
    api = {"enableSpotAndMarginTrading": True, "enableWithdrawals": False,
           "permitsUniversalTransfer": False, "enableInternalTransfer": False,
           "enableMargin": False, "enableFutures": False,
           "enablePortfolioMarginTrading": False, "ipRestrict": True}
    p = perms_from_api(api)
    assert p.enable_spot_and_margin_trading and p.ip_restrict
