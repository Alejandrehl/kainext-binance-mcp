from decimal import Decimal
from kainext_binance_mcp.models import CanonicalOrder, OrderPreview
from kainext_binance_mcp_confirmer.dialog import render_dialog_text, parse_osascript_result

def test_render_shows_env_and_effective_values():
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quote_quantity=Decimal("10"), env="mainnet")
    prev = OrderPreview(effective_qty=Decimal("0.0002"), price=None, est_notional=Decimal("10"),
                        est_commission=Decimal("0.01"), env="mainnet", feasible=True)
    text = render_dialog_text(o, prev)
    assert "MAINNET" in text and "PLATA REAL" in text and "BTCUSDT" in text and "0.0002" in text

def test_parse_confirm_and_cancel():
    assert parse_osascript_result(returncode=0, stdout="button returned:Confirmar") is True
    assert parse_osascript_result(returncode=1, stdout="") is False  # cancel/esc/timeout
