"""Round-trip REAL sobre un Unix socket temporal (spec §4.3b).

Levantamos `serve` en un hilo con un store real, client/estimator mock y un
`ask_confirmation` stub que devuelve False (para NO ejecutar). Verificamos:
- register(order) → intent_id; status(intent_id) → pending o rejected (nunca executed).
- un mensaje type:"execute" es rechazado y NO produce ejecución.
- IpcClient ante socket inexistente lanza IpcUnavailableError.
"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kainext_binance_mcp.intents import IntentStore
from kainext_binance_mcp.ipc import IpcClient, IpcUnavailableError, encode_msg, serve
from kainext_binance_mcp.models import CanonicalOrder, OrderPreview


def _order() -> CanonicalOrder:
    return CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                          quote_quantity=Decimal("10"), env="testnet")


def _feasible_preview() -> OrderPreview:
    return OrderPreview(effective_qty=Decimal("0.0002"), price=None, est_notional=Decimal("10"),
                        est_commission=Decimal("0.01"), env="testnet", feasible=True)


@pytest.fixture
def running_socket(monkeypatch):
    """Arranca serve() en un hilo daemon sobre un socket temporal.
    ask_confirmation se stubea a False → los intents terminan en 'rejected', nunca 'executed'."""
    tmpdir = tempfile.mkdtemp(prefix="kbm-ipc-")
    sock_path = os.path.join(tmpdir, "confirmer.sock")

    # Stub del clic: SIEMPRE False (no ejecutar).
    import kainext_binance_mcp_confirmer.dialog as dialog
    monkeypatch.setattr(dialog, "ask_confirmation", lambda text: False)

    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    client = MagicMock()
    estimator = MagicMock()
    estimator.estimate.return_value = _feasible_preview()
    lock = threading.Lock()

    t = threading.Thread(
        target=serve, args=(sock_path, store, client, "nonce-test", lock, estimator), daemon=True)
    t.start()

    # Esperar a que el socket ACEPTE conexiones (que el path exista no basta: en
    # macOS/py3.13 el archivo aparece tras bind() pero antes de listen() → refused).
    ready = False
    for _ in range(200):
        if os.path.exists(sock_path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(sock_path)
            except OSError:
                pass
            else:
                ready = True
                break
            finally:
                probe.close()
        time.sleep(0.01)
    assert ready, "el confirmador no aceptó conexiones a tiempo"

    yield sock_path, store, client


def _wait_state(store, iid, *, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = store.get(iid).state
        if st != "pending":
            return st
        time.sleep(0.01)
    return store.get(iid).state


def test_register_then_status_never_executes(running_socket):
    sock_path, store, client = running_socket
    cli = IpcClient(sock_path)

    intent_id, expires_at = cli.register(_order())
    assert intent_id and isinstance(expires_at, int)

    # El confirmador re-valida y muestra el diálogo; con ask_confirmation=False → rejected.
    final = _wait_state(store, intent_id)
    assert final in ("pending", "rejected")
    assert final != "executed"
    client.create_order.assert_not_called()

    out = cli.status(intent_id)
    assert out["intent_id"] == intent_id
    assert out["state"] in ("pending", "rejected")


def test_status_unknown_intent(running_socket):
    sock_path, _store, _client = running_socket
    cli = IpcClient(sock_path)
    out = cli.status("no-existe")
    assert out["state"] == "unknown"


def test_execute_type_is_rejected_and_changes_nothing(running_socket):
    sock_path, store, client = running_socket

    # Primero un register legítimo para tener un intent en juego.
    cli = IpcClient(sock_path)
    intent_id, _ = cli.register(_order())
    _wait_state(store, intent_id)

    # Mensaje malicioso type:"execute" directo por el socket (IpcClient no tiene execute).
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(sock_path)
    conn.sendall(encode_msg({"v": 1, "type": "execute", "intent_id": intent_id}).encode())
    resp = conn.recv(4096).decode()
    conn.close()

    assert "error" in resp.lower()
    # Nada se ejecutó: ningún create_order y ningún intent quedó executed.
    client.create_order.assert_not_called()
    assert store.get(intent_id).state != "executed"


def test_anti_spam_rejects_when_too_many_pending(monkeypatch):
    """Con max_pending bajo y ask_confirmation que cuelga (no resuelve el intent),
    el confirmador rechaza nuevos register: anti-spam §4.3c."""
    tmpdir = tempfile.mkdtemp(prefix="kbm-ipc-spam-")
    sock_path = os.path.join(tmpdir, "confirmer.sock")

    block = threading.Event()
    import kainext_binance_mcp_confirmer.dialog as dialog
    # El diálogo se queda bloqueado → los intents quedan 'pending' (diálogo abierto).
    monkeypatch.setattr(dialog, "ask_confirmation", lambda text: block.wait(timeout=5) or False)

    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    client = MagicMock()
    estimator = MagicMock()
    estimator.estimate.return_value = _feasible_preview()
    lock = threading.Lock()

    t = threading.Thread(
        target=serve,
        kwargs=dict(socket_path=sock_path, store=store, client=client, nonce="n",
                    dialog_lock=lock, estimator=estimator, max_pending=1),
        daemon=True)
    t.start()
    for _ in range(200):
        if os.path.exists(sock_path):
            break
        time.sleep(0.01)

    cli = IpcClient(sock_path)
    cli.register(_order())  # primero ocupa el único cupo (queda pending, diálogo bloqueado)
    # Esperar a que pending_count llegue a 1.
    for _ in range(200):
        if store.pending_count() >= 1:
            break
        time.sleep(0.01)
    with pytest.raises(Exception) as ei:  # IpcProtocolError con el mensaje anti-spam
        cli.register(_order())
    assert "anti-spam" in str(ei.value).lower()
    block.set()


def test_client_raises_when_socket_missing(tmp_path):
    cli = IpcClient(str(tmp_path / "no-such.sock"))
    with pytest.raises(IpcUnavailableError):
        cli.register(_order())
    with pytest.raises(IpcUnavailableError):
        cli.status("x")


def test_early_disconnect_does_not_kill_server(running_socket):
    """Un cliente local que conecta y cierra sin hablar (o a mitad de la respuesta) NO debe
    tumbar el loop del confirmador — antes un BrokenPipeError mataba el hilo (DoS local)."""
    sock_path, store, client = running_socket
    for _ in range(3):
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.connect(sock_path)
        probe.close()  # desconexión temprana, sin request
    # El server sigue vivo: un register normal funciona después de los cierres abruptos.
    ipc = IpcClient(sock_path)
    intent_id, _ = ipc.register(_order())
    assert isinstance(intent_id, str) and intent_id
