import json
from decimal import Decimal
from unittest.mock import MagicMock
from binance.exceptions import BinanceAPIException
from kainext_binance_mcp.models import OrderPreview
from kainext_binance_mcp.tools.write import spot_order_propose, spot_order_status


def test_propose_registers_canonical_and_returns_intent():
    ipc = MagicMock()
    ipc.register.return_value = ("intent-1", 1700000000)  # (intent_id, expires_at)
    market = MagicMock()  # pre-validación local
    market.estimate.return_value = OrderPreview(
        effective_qty=Decimal("0.0002"), price=None, est_notional=Decimal("10"),
        est_commission=Decimal("0.01"), env="testnet", feasible=True)
    out = spot_order_propose(ipc=ipc, market=market, symbol="BTCUSDT", side="BUY",
                             type="MARKET", quote_quantity=Decimal("10"), env="testnet")
    assert out.intent_id == "intent-1"
    # El server registra el CanonicalOrder; jamás coloca la orden:
    args = ipc.register.call_args[0][0]
    assert args.symbol == "BTCUSDT" and args.quote_quantity == Decimal("10")


def test_status_relays():
    ipc = MagicMock()
    ipc.status.return_value = {"intent_id": "i1", "state": "pending"}
    out = spot_order_status(ipc=ipc, intent_id="i1")
    assert out.state == "pending"


def test_cancel_propose_skips_if_not_cancelable():
    ipc = MagicMock(); client = MagicMock()
    client.get_order.return_value = {"status": "FILLED"}
    from kainext_binance_mcp.tools.write import cancel_order_propose
    out = cancel_order_propose(ipc=ipc, client=client, symbol="BTCUSDT", order_id=1, env="testnet")
    assert out.error is not None and "cancelable" in out.error.message.lower()
    ipc.register_cancel.assert_not_called()


def test_cancel_propose_registers_when_cancelable():
    ipc = MagicMock(); client = MagicMock()
    client.get_order.return_value = {"status": "NEW"}
    ipc.register_cancel.return_value = ("intent-c1", 1700000000)
    from kainext_binance_mcp.tools.write import cancel_order_propose
    out = cancel_order_propose(ipc=ipc, client=client, symbol="BTCUSDT", order_id=1, env="testnet")
    assert out.error is None and out.intent_id == "intent-c1"
    ipc.register_cancel.assert_called_once()


class _Resp:
    def __init__(self, text):
        self.text = text
        self.request = None


def test_cancel_propose_handles_get_order_raising_without_traceback():
    """A2: client.get_order lanza un BinanceAPIException REAL (-2013) → cancel_order_propose
    devuelve OrderProposal con error mapeado y scrubbeado, sin reventar ni crear intent."""
    ipc = MagicMock()
    client = MagicMock()
    client.API_KEY = "READ_KEY_LEAK_abc"; client.API_SECRET = "READ_SECRET_def"
    raw = json.dumps({"code": -2013, "msg": "Order does not exist for key READ_KEY_LEAK_abc"})
    client.get_order.side_effect = BinanceAPIException(_Resp(raw), 400, raw)  # tipo real
    from kainext_binance_mcp.tools.write import cancel_order_propose
    out = cancel_order_propose(ipc=ipc, client=client, symbol="BTCUSDT", order_id=1, env="testnet")
    assert out.intent_id is None
    assert out.error is not None and out.error.code == -2013
    assert "READ_KEY_LEAK_abc" not in out.error.message  # scrubbeado
    assert "no existe" in out.error.message.lower()      # mapeado (-2013)
    ipc.register_cancel.assert_not_called()


def test_cancel_status_relays():
    ipc = MagicMock()
    ipc.status.return_value = {"intent_id": "ic1", "state": "pending"}
    from kainext_binance_mcp.tools.write import cancel_order_status
    out = cancel_order_status(ipc=ipc, intent_id="ic1")
    assert out.state == "pending"


def test_propose_returns_tool_error_when_confirmer_down():
    """Confirmador caído: la tool devuelve ToolError (mismo contrato que cancel), nunca
    una excepción cruda al modelo."""
    from decimal import Decimal
    from unittest.mock import MagicMock
    from kainext_binance_mcp.ipc import IpcUnavailableError
    from kainext_binance_mcp.tools.write import cancel_order_propose, spot_order_propose

    ipc = MagicMock()
    ipc.register.side_effect = IpcUnavailableError("confirmer not running")
    market = MagicMock()
    prop = spot_order_propose(ipc=ipc, market=market, symbol="BTCUSDT", side="BUY",
                              type="MARKET", env="testnet", quote_quantity=Decimal("10"))
    assert prop.error is not None and prop.error.code == "ipc_unavailable"
    assert prop.intent_id is None

    ipc2 = MagicMock()
    ipc2.register_cancel.side_effect = IpcUnavailableError("confirmer not running")
    client = MagicMock(); client.get_order.return_value = {"status": "NEW"}
    prop2 = cancel_order_propose(ipc=ipc2, client=client, symbol="BTCUSDT",
                                 order_id=1, env="testnet")
    assert prop2.error is not None and prop2.error.code == "ipc_unavailable"
