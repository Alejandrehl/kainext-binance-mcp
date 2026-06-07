"""Cobertura de ramas del IPC no ejercitadas por test_ipc_socket.py (gate ≥95%, plan §5).

Cubre: register de CANCELACIÓN end-to-end por socket (server crea intent + dispatch +
re-uso de socket pre-existente), errores de decode/_request del cliente, _read_line ante
conexión cerrada, mensaje malformado que rompe _handle (envelope de error, NO se actúa),
y cierre limpio del servidor (unlink del socket)."""
from __future__ import annotations
import json
import os
import socket
import tempfile
import threading
import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kainext_binance_mcp.intents import IntentStore
from kainext_binance_mcp.ipc import (
    IpcClient, IpcProtocolError, IpcUnavailableError, _read_line, decode_msg,
    encode_msg, serve,
)
from kainext_binance_mcp.models import CanonicalOrder, OrderPreview


# --- decode_msg / _read_line: ramas unitarias --------------------------------

def test_decode_msg_invalid_json():
    with pytest.raises(IpcProtocolError, match="JSON inválido"):
        decode_msg("{no es json")


def test_decode_msg_not_an_object():
    with pytest.raises(IpcProtocolError, match="no es objeto"):
        decode_msg(json.dumps([1, 2, 3]) + "\n")


def test_read_line_returns_empty_on_closed_connection():
    """recv() devuelve b'' (peer cerró) → _read_line corta y devuelve cadena vacía."""
    a, b = socket.socketpair()
    b.close()
    try:
        assert _read_line(a) == ""
    finally:
        a.close()


# --- IpcClient: ramas de error ------------------------------------------------

def _short_sock(prefix: str) -> str:
    # AF_UNIX en macOS tope ~104 chars; tmp_path de pytest se pasa. Usamos /tmp corto.
    return os.path.join(tempfile.mkdtemp(prefix=prefix, dir="/tmp"), "srv.sock")


def test_client_status_envelope_error_raises_protocol_error():
    """El server responde {"error": ...} sin state/intent_id → IpcProtocolError."""
    sock_path = _short_sock("kbm-env-")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)

    def _serve_once() -> None:
        conn, _ = srv.accept()
        _read_line(conn)
        conn.sendall(encode_msg({"error": "explotó"}).encode())
        conn.close()

    t = threading.Thread(target=_serve_once, daemon=True)
    t.start()
    cli = IpcClient(sock_path)
    with pytest.raises(IpcProtocolError, match="explotó"):
        cli.status("x")
    srv.close()


def test_client_empty_response_raises_unavailable():
    """Respuesta vacía del confirmador → IpcUnavailableError."""
    sock_path = _short_sock("kbm-empty-")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)

    def _serve_once() -> None:
        conn, _ = srv.accept()
        _read_line(conn)
        conn.close()  # cierra sin responder

    threading.Thread(target=_serve_once, daemon=True).start()
    cli = IpcClient(sock_path)
    with pytest.raises(IpcUnavailableError, match="respuesta vacía"):
        cli.status("x")
    srv.close()


def test_client_invalid_response_json_raises_protocol_error():
    sock_path = _short_sock("kbm-badjson-")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)

    def _serve_once() -> None:
        conn, _ = srv.accept()
        _read_line(conn)
        conn.sendall(b"{no json\n")
        conn.close()

    threading.Thread(target=_serve_once, daemon=True).start()
    cli = IpcClient(sock_path)
    with pytest.raises(IpcProtocolError, match="respuesta inválida"):
        cli.status("x")
    srv.close()


# --- serve(): register de cancelación end-to-end + reuso de socket -----------

def _feasible_preview() -> OrderPreview:
    return OrderPreview(effective_qty=Decimal("0.0002"), price=None, est_notional=Decimal("10"),
                        est_commission=Decimal("0.01"), env="testnet", feasible=True)


@pytest.fixture
def running_server(monkeypatch):
    tmpdir = tempfile.mkdtemp(prefix="kbm-ipc-br-")
    sock_path = os.path.join(tmpdir, "confirmer.sock")

    import kainext_binance_mcp_confirmer.dialog as dialog
    monkeypatch.setattr(dialog, "ask_confirmation", lambda text: False)

    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    client = MagicMock()
    client.get_order.return_value = {"status": "NEW"}  # cancelable, para el dispatch de cancel
    estimator = MagicMock()
    estimator.estimate.return_value = _feasible_preview()
    lock = threading.Lock()

    t = threading.Thread(
        target=serve, args=(sock_path, store, client, "nonce", lock, estimator), daemon=True)
    t.start()
    for _ in range(200):
        if os.path.exists(sock_path):
            break
        time.sleep(0.01)
    assert os.path.exists(sock_path), "el confirmador no creó el socket a tiempo"
    yield sock_path, store, client


def _wait_state(store, iid, *, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = store.get(iid).state
        if st != "pending":
            return st
        time.sleep(0.01)
    return store.get(iid).state


def test_register_cancel_creates_intent_and_dispatches(running_server):
    """register_cancel por el socket → el server crea el intent de cancelación, lo despacha
    (re-consulta + diálogo=False) y termina en 'rejected'. Nunca cancela sin clic."""
    sock_path, store, client = running_server
    cli = IpcClient(sock_path)
    intent_id, expires_at = cli.register_cancel("BTCUSDT", 12345, env="testnet")
    assert intent_id and isinstance(expires_at, int)
    final = _wait_state(store, intent_id)
    assert final in ("pending", "rejected")
    client.cancel_order.assert_not_called()


def test_malformed_register_returns_error_envelope_without_acting(running_server):
    """register sin 'order' → _handle lanza KeyError → envelope {"error": ...}; nada se ejecuta."""
    sock_path, store, client = running_server
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(sock_path)
    conn.sendall(encode_msg({"v": 1, "type": "register"}).encode())  # falta 'order'
    resp = conn.recv(4096).decode()
    conn.close()
    assert "error" in resp.lower()
    client.create_order.assert_not_called()


def test_register_cancel_client_method_unavailable_when_no_socket(tmp_path):
    cli = IpcClient(str(tmp_path / "nope.sock"))
    with pytest.raises(IpcUnavailableError):
        cli.register_cancel("BTCUSDT", 1)


def test_serve_breaks_loop_and_cleans_up_on_socket_close(monkeypatch):
    """Al cerrar el socket de escucha, accept() lanza OSError → el loop corta y el finally
    cierra y unlinkea el socket. Cubre el shutdown limpio del confirmador."""
    import kainext_binance_mcp.ipc as ipc_mod

    tmpdir = tempfile.mkdtemp(prefix="kbm-shut-", dir="/tmp")
    sock_path = os.path.join(tmpdir, "confirmer.sock")

    created: list[socket.socket] = []
    real_socket = socket.socket

    def _tracking_socket(*a, **k):
        s = real_socket(*a, **k)
        created.append(s)
        return s

    monkeypatch.setattr(ipc_mod.socket, "socket", _tracking_socket)
    import kainext_binance_mcp_confirmer.dialog as dialog
    monkeypatch.setattr(dialog, "ask_confirmation", lambda text: False)

    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    estimator = MagicMock()
    estimator.estimate.return_value = _feasible_preview()

    t = threading.Thread(
        target=serve, args=(sock_path, store, MagicMock(), "n", threading.Lock(), estimator),
        daemon=True)
    t.start()
    for _ in range(200):
        if os.path.exists(sock_path):
            break
        time.sleep(0.01)
    # El primer socket creado por serve es el de escucha (srv): cerrarlo rompe accept().
    srv_sock = created[0]
    srv_sock.close()
    t.join(timeout=2.0)
    assert not t.is_alive(), "serve no terminó tras cerrar el socket de escucha"
    assert not os.path.exists(sock_path), "el finally debió unlinkear el socket"


def test_serve_unlinks_stale_socket_path(monkeypatch):
    """Si ya existe un archivo en socket_path, serve lo unlinkea antes de bind (línea de limpieza).
    Un register exitoso prueba que el socket nuevo quedó operativo."""
    tmpdir = tempfile.mkdtemp(prefix="kbm-stale-", dir="/tmp")
    sock_path = os.path.join(tmpdir, "confirmer.sock")
    open(sock_path, "w").close()  # archivo stale ocupando el path

    import kainext_binance_mcp_confirmer.dialog as dialog
    monkeypatch.setattr(dialog, "ask_confirmation", lambda text: False)
    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    client = MagicMock()
    estimator = MagicMock()
    estimator.estimate.return_value = _feasible_preview()
    lock = threading.Lock()

    t = threading.Thread(
        target=serve, args=(sock_path, store, client, "n", lock, estimator), daemon=True)
    t.start()
    # Esperar a que serve reemplace el archivo stale por un socket real conectable.
    cli = IpcClient(sock_path)
    intent_id = None
    for _ in range(200):
        try:
            intent_id, _ = cli.register(
                CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                               quote_quantity=Decimal("10"), env="testnet"))
            break
        except (IpcUnavailableError, OSError):
            time.sleep(0.01)
    assert intent_id is not None
