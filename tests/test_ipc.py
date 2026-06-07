import pytest
from decimal import Decimal
from kainext_binance_mcp.models import CanonicalOrder
from kainext_binance_mcp.ipc import encode_msg, decode_msg, IpcProtocolError

def test_register_roundtrip():
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quote_quantity=Decimal("10"), env="testnet")
    line = encode_msg({"v": 1, "type": "register", "order": o.model_dump(mode="json")})
    msg = decode_msg(line)
    assert msg["type"] == "register" and msg["order"]["symbol"] == "BTCUSDT"

def test_rejects_unknown_type():
    line = encode_msg({"v": 1, "type": "execute"})  # tipo inválido
    with pytest.raises(IpcProtocolError):
        decode_msg(line)

def test_rejects_bad_version():
    import json
    with pytest.raises(IpcProtocolError):
        decode_msg(json.dumps({"v": 99, "type": "status"}) + "\n")
