"""A1 — audit log de órdenes ejecutadas (spec §4.10)."""
import json
import os
import stat
from decimal import Decimal
from unittest.mock import MagicMock

from kainext_binance_mcp.models import CanonicalOrder
from kainext_binance_mcp_confirmer.audit import append_audit_entry
from kainext_binance_mcp_confirmer.executor import handle_cancel_intent, handle_intent


def test_append_audit_entry_writes_expected_line_without_secrets(tmp_path):
    path = str(tmp_path / "sub" / "audit.log")
    append_audit_entry(
        path=path, intent_id="i1", client_order_id="kbm_abc", order_id=42,
        symbol="BTCUSDT", side="BUY", effective_qty=Decimal("0.0002"),
        price=Decimal("50000"), env="testnet")
    with open(path) as f:
        lines = f.read().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["intent_id"] == "i1"
    assert entry["client_order_id"] == "kbm_abc"
    assert entry["order_id"] == 42
    assert entry["symbol"] == "BTCUSDT"
    assert entry["side"] == "BUY"
    assert entry["effective_qty"] == "0.0002"
    assert entry["price"] == "50000"
    assert entry["env"] == "testnet"
    assert "timestamp" in entry
    # Sin secretos: el dump no contiene claves de api key/secret/nonce.
    raw = lines[0].lower()
    assert "secret" not in raw and "api_key" not in raw and "nonce" not in raw
    # Archivo 0600.
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, oct(mode)


def test_append_rejects_non_serializable_value(tmp_path):
    """El serializador sólo conoce Decimal; un tipo raro dispara TypeError (no escribe basura)."""
    import pytest
    with pytest.raises(TypeError):
        append_audit_entry(
            path=str(tmp_path / "audit.log"), intent_id="i1", client_order_id="c",
            order_id=1, symbol="BTCUSDT", side="BUY", effective_qty=object(),  # no serializable
            price=None, env="testnet")


def test_append_is_additive(tmp_path):
    path = str(tmp_path / "audit.log")
    for i in range(3):
        append_audit_entry(path=path, intent_id=f"i{i}", client_order_id="c", order_id=i,
                           symbol="BTCUSDT", side="BUY", effective_qty=Decimal("1"),
                           price=None, env="testnet")
    with open(path) as f:
        assert len(f.read().splitlines()) == 3


def test_executor_writes_audit_line_after_mark_executed(tmp_path):
    """El executor appendea al audit log tras mark_executed. `effective_qty` = cantidad ORDENADA
    (lo colocado), `executed_qty` = lo llenado. Para una LIMIT resting executed_qty=0 pero la
    orden igual debe quedar trazada con su cantidad ordenada (no 0)."""
    path = str(tmp_path / "audit.log")
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=Decimal("49500"))
    # Orden LIMIT que quedó NEW (resting): executedQty=0, distinto de la cantidad ordenada.
    client.create_order.return_value = {"orderId": 9, "clientOrderId": "kbm_x",
        "status": "NEW", "executedQty": "0", "cummulativeQuoteQty": "0", "fills": []}
    order = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                           quantity=Decimal("0.0002"), price=Decimal("49500"),
                           time_in_force="GTC", env="testnet")
    handle_intent(order=order, intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="super-secret-nonce",
                  audit_path=path)
    store.mark_executed.assert_called_once()
    with open(path) as f:
        line = f.read().strip()
    entry = json.loads(line)
    assert entry["order_id"] == 9 and entry["client_order_id"] == "kbm_x"
    # Bug fix: registra la cantidad ORDENADA (0.0002), NO la ejecutada (0) que tenía antes.
    assert entry["effective_qty"] == "0.0002"
    assert entry["executed_qty"] == "0"
    assert entry["env"] == "testnet"
    assert "super-secret-nonce" not in line  # el nonce NUNCA va al audit


def test_audit_failure_never_breaks_execution(monkeypatch, tmp_path):
    """A1 (best-effort): si el audit append revienta, la orden YA quedó executed; el fallo
    del audit no debe propagar ni revertir el estado."""
    import kainext_binance_mcp_confirmer.audit as audit_mod

    def boom(**kw):
        raise OSError("disco lleno")

    monkeypatch.setattr(audit_mod, "append_audit_entry", boom)
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    client.create_order.return_value = {"orderId": 9, "clientOrderId": "kbm_x",
        "status": "FILLED", "executedQty": "0.0002", "cummulativeQuoteQty": "10", "fills": []}
    order = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                           quote_quantity=Decimal("10"), env="testnet")
    handle_intent(order=order, intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n",
                  audit_path=str(tmp_path / "audit.log"))
    store.mark_executed.assert_called_once()  # ejecución intacta pese al fallo del audit
    store.mark_failed.assert_not_called()


def test_cancel_executor_writes_audit_line_after_mark_executed(tmp_path):
    """A1: una cancelación ejecutada deja su línea de audit (action=CANCEL), sin secretos."""
    path = str(tmp_path / "audit.log")
    client = MagicMock(); store = MagicMock()
    client.get_order.return_value = {"status": "NEW"}  # cancelable (TOCTOU recheck)
    client.cancel_order.return_value = {"orderId": 77, "status": "CANCELED"}
    # python-binance guarda la key/secret en estos atributos: deben NO filtrarse al audit.
    client.API_KEY = "super-secret-key"
    client.API_SECRET = "super-secret-secret"
    handle_cancel_intent(symbol="BTCUSDT", order_id=77, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True,
                         audit_path=path)
    store.mark_executed.assert_called_once()
    with open(path) as f:
        line = f.read().strip()
    entry = json.loads(line)
    assert entry["action"] == "CANCEL"
    assert entry["intent_id"] == "c1"
    assert entry["order_id"] == 77
    assert entry["symbol"] == "BTCUSDT"
    assert entry["env"] == "testnet"
    assert "timestamp" in entry
    # Sin secretos: ni key/secret del client ni la palabra "secret"/"api_key"/"nonce".
    assert "super-secret-key" not in line and "super-secret-secret" not in line
    raw = line.lower()
    assert "secret" not in raw and "api_key" not in raw and "nonce" not in raw


def test_cancel_executor_does_not_write_audit_when_no_path(tmp_path):
    """Sin audit_path (default None) una cancelación no escribe nada."""
    client = MagicMock(); store = MagicMock()
    client.get_order.return_value = {"status": "NEW"}
    client.cancel_order.return_value = {"orderId": 77, "status": "CANCELED"}
    handle_cancel_intent(symbol="BTCUSDT", order_id=77, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True)
    store.mark_executed.assert_called_once()
    assert not list(tmp_path.iterdir())


def test_cancel_audit_failure_never_breaks_cancellation(monkeypatch, tmp_path):
    """A1 (best-effort): si el audit revienta, la cancelación YA quedó executed; no propaga."""
    import kainext_binance_mcp_confirmer.audit as audit_mod

    def boom(**kw):
        raise OSError("disco lleno")

    monkeypatch.setattr(audit_mod, "append_audit_entry", boom)
    client = MagicMock(); store = MagicMock()
    client.get_order.return_value = {"status": "NEW"}
    client.cancel_order.return_value = {"orderId": 77, "status": "CANCELED"}
    handle_cancel_intent(symbol="BTCUSDT", order_id=77, env="testnet", intent_id="c1",
                         store=store, client=client, confirm=lambda text: True,
                         audit_path=str(tmp_path / "audit.log"))
    store.mark_executed.assert_called_once()
    store.mark_failed.assert_not_called()


def test_executor_does_not_write_audit_when_no_path(tmp_path):
    """Sin audit_path (default None) no se escribe nada (back-compat / tests sin side effects)."""
    client = MagicMock(); store = MagicMock(); est = MagicMock()
    est.estimate.return_value = MagicMock(feasible=True, effective_qty=Decimal("0.0002"),
                                          price=None)
    client.create_order.return_value = {"orderId": 9, "clientOrderId": "kbm_x",
        "status": "FILLED", "executedQty": "0.0002", "cummulativeQuoteQty": "10", "fills": []}
    order = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                           quote_quantity=Decimal("10"), env="testnet")
    handle_intent(order=order, intent_id="i1", store=store, client=client,
                  estimator=est, confirm=lambda text: True, nonce="n")
    assert not list(tmp_path.iterdir())  # no se creó ningún archivo
