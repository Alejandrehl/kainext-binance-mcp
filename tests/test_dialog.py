from decimal import Decimal
from kainext_binance_mcp.models import CanonicalOrder, OrderPreview
from kainext_binance_mcp_confirmer.dialog import (escape_applescript, parse_osascript_result,
                                                  render_dialog_text)

def test_render_shows_env_and_effective_values():
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quote_quantity=Decimal("10"), env="mainnet")
    prev = OrderPreview(effective_qty=Decimal("0.0002"), price=None, est_notional=Decimal("10"),
                        est_commission=Decimal("0.01"), env="mainnet", feasible=True)
    text = render_dialog_text(o, prev)
    assert "MAINNET" in text and "REAL MONEY" in text and "BTCUSDT" in text and "0.0002" in text

def test_parse_confirm_and_cancel():
    assert parse_osascript_result(returncode=0, stdout="button returned:Confirm") is True
    assert parse_osascript_result(returncode=1, stdout="") is False  # cancel/esc/timeout

def test_parse_real_osascript_formats_with_giving_up():
    # Con `giving up after`, osascript anexa ", gave up:false" — el formato REAL del clic.
    assert parse_osascript_result(
        returncode=0, stdout="button returned:Confirm, gave up:false\n") is True
    assert parse_osascript_result(
        returncode=0, stdout="button returned:Cancel, gave up:false\n") is False
    # Timeout (giving up) => gave up:true, aunque exit sea 0.
    assert parse_osascript_result(returncode=0, stdout="gave up:true\n") is False
    # Cancelar/Esc con cancel button => exit != 0 (User canceled -128).
    assert parse_osascript_result(returncode=1, stdout="") is False


def test_escape_applescript_backslash_then_quote():
    # backslash primero (si no, re-escaparia las comillas ya escapadas)
    assert escape_applescript('say "hi"') == 'say \\"hi\\"'
    assert escape_applescript("back\\slash") == "back\\\\slash"
    assert escape_applescript('mix\\"end') == 'mix\\\\\\"end'
