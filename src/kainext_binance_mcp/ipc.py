"""Protocolo IPC server↔confirmador (spec §4.3b). JSON line-delimited.
Sólo 'register' y 'status'. NO existe 'execute'/'approve': la ejecución
sólo nace del clic en el diálogo del confirmador.

Wire format (spec §4.3b):
  register order  → {"v":1,"type":"register","kind":"order","order": <CanonicalOrder json>}
  register cancel → {"v":1,"type":"register","kind":"cancel","symbol":...,"order_id":...,"env":...}
  status          → {"v":1,"type":"status","intent_id":...}
Respuestas:
  register → {"intent_id":..., "expires_at":...}
  status   → OrderStatus json ({intent_id, state, result, error})
  error    → {"error": "<motivo>"}  (también ante type desconocido: NO se actúa)
"""
from __future__ import annotations
import json
import os
import socket
import threading
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from kainext_binance_mcp.models import CanonicalOrder

PROTOCOL_VERSION = 1
_ALLOWED_TYPES = {"register", "status"}
_MAX_PENDING = 5  # anti-spam: tope de intents pendientes en ventana viva (spec §4.3c)


class IpcProtocolError(Exception):
    pass


class IpcUnavailableError(Exception):
    """El confirmador no está disponible (socket inexistente o conexión fallida)."""


def encode_msg(msg: dict[str, Any]) -> str:
    return json.dumps(msg, separators=(",", ":")) + "\n"


def decode_msg(line: str) -> dict[str, Any]:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        raise IpcProtocolError(f"invalid JSON: {e}") from e
    if not isinstance(msg, dict):
        raise IpcProtocolError("mensaje no es objeto")
    if msg.get("v") != PROTOCOL_VERSION:
        raise IpcProtocolError(f"unsupported protocol version: {msg.get('v')}")
    if msg.get("type") not in _ALLOWED_TYPES:
        raise IpcProtocolError(f"type no permitido: {msg.get('type')}")
    return msg


def _read_line(conn: socket.socket) -> str:
    # B4 (nota): un request por conexión efímera — el cliente abre, manda UNA línea, lee UNA
    # respuesta y cierra. No hay framing multi-mensaje sobre la misma conexión (no hace falta
    # en capa 1); por eso leemos hasta el primer '\n' (o EOF) y no bucleamos por más mensajes.
    chunks: list[bytes] = []
    while True:
        b = conn.recv(4096)
        if not b:
            break
        chunks.append(b)
        if b"\n" in b:
            break
    return b"".join(chunks).decode("utf-8")


class IpcClient:
    """Cliente IPC (lo usa el MCP server). Una conexión efímera por request."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path

    def _request(self, msg: dict[str, Any]) -> dict[str, Any]:
        if not os.path.exists(self.socket_path):
            raise IpcUnavailableError(
                "confirmer unavailable: start `kainext-binance-mcp-confirmer` "
                f"(socket {self.socket_path} does not exist)")
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.connect(self.socket_path)
        except OSError as e:
            raise IpcUnavailableError(f"confirmer unavailable: {e}") from e
        try:
            conn.sendall(encode_msg(msg).encode("utf-8"))
            resp = _read_line(conn)
        finally:
            conn.close()
        if not resp:
            raise IpcUnavailableError("confirmer unavailable: empty response")
        try:
            data = json.loads(resp)
        except json.JSONDecodeError as e:
            raise IpcProtocolError(f"invalid response from confirmer: {e}") from e
        # Envelope de error del servidor IPC: {"error": "..."} y sin payload de estado.
        # (OrderStatus también lleva una clave "error", pero junto a "state".)
        if isinstance(data, dict) and "error" in data and "state" not in data \
                and "intent_id" not in data:
            raise IpcProtocolError(str(data["error"]))
        return cast("dict[str, Any]", data)

    def register(self, order: CanonicalOrder) -> tuple[str, int]:
        data = self._request({"v": PROTOCOL_VERSION, "type": "register", "kind": "order",
                              "order": order.model_dump(mode="json")})
        return data["intent_id"], int(data["expires_at"])

    def register_cancel(self, symbol: str, order_id: int, env: str = "testnet") -> tuple[str, int]:
        data = self._request({"v": PROTOCOL_VERSION, "type": "register", "kind": "cancel",
                              "symbol": symbol, "order_id": order_id, "env": env})
        return data["intent_id"], int(data["expires_at"])

    def status(self, intent_id: str) -> dict[str, Any]:
        return self._request({"v": PROTOCOL_VERSION, "type": "status", "intent_id": intent_id})


def serve(socket_path: str, store: Any, client: Any, nonce: str,
          dialog_lock: "threading.Lock", estimator: Any,
          *, max_pending: int = _MAX_PENDING, confirmer_env: str = "testnet",
          audit_path: str | None = None) -> None:
    """Servidor IPC (lo corre el confirmador). Crea el Unix socket (carpeta 0700,
    socket 0600), acepta conexiones y atiende register/status. La ejecución NUNCA
    nace de un mensaje: sólo de `handle_intent` tras el clic en el diálogo (spec §4.3)."""
    # Import diferido para no acoplar el server (read-only) al confirmador.
    from kainext_binance_mcp.models import CanonicalOrder
    from kainext_binance_mcp_confirmer.dialog import ask_confirmation
    from kainext_binance_mcp_confirmer.executor import handle_intent, handle_cancel_intent

    directory = os.path.dirname(socket_path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(socket_path)
    os.chmod(socket_path, 0o600)
    srv.listen(8)

    def _dispatch(order: CanonicalOrder, intent_id: str) -> None:
        with dialog_lock:  # anti-spam §4.3c: un diálogo a la vez
            handle_intent(order=order, intent_id=intent_id, store=store, client=client,
                          estimator=estimator, confirm=ask_confirmation, nonce=nonce,
                          confirmer_env=confirmer_env, audit_path=audit_path)

    def _dispatch_cancel(symbol: str, order_id: int, env: str, intent_id: str) -> None:
        with dialog_lock:
            handle_cancel_intent(symbol=symbol, order_id=order_id, env=env, intent_id=intent_id,
                                 store=store, client=client, confirm=ask_confirmation,
                                 confirmer_env=confirmer_env, audit_path=audit_path)

    def _handle(msg: dict[str, Any]) -> dict[str, Any]:
        mtype = msg["type"]
        if mtype == "register":
            if store.pending_count() >= max_pending:
                return {"error": "anti-spam: demasiados intents pendientes; esperá"}
            kind = msg.get("kind", "order")
            if kind == "cancel":
                symbol = msg["symbol"]
                order_id = int(msg["order_id"])
                env = msg.get("env", "testnet")
                iid = store.register_cancel(symbol, order_id)
                expires_at = store.get(iid).expires_at
                threading.Thread(target=_dispatch_cancel,
                                 args=(symbol, order_id, env, iid), daemon=True).start()
                return {"intent_id": iid, "expires_at": expires_at}
            order = CanonicalOrder(**msg["order"])
            iid = store.register(order)
            expires_at = store.get(iid).expires_at
            threading.Thread(target=_dispatch, args=(order, iid), daemon=True).start()
            return {"intent_id": iid, "expires_at": expires_at}
        # status
        intent_id = msg["intent_id"]
        try:
            it = store.get(intent_id)
        except KeyError:
            return {"intent_id": intent_id, "state": "unknown", "result": None, "error": None}
        return {
            "intent_id": intent_id,
            "state": it.state,
            "result": it.result.model_dump(mode="json") if it.result is not None else None,
            "error": it.error.model_dump(mode="json") if it.error is not None else None,
        }

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break  # socket cerrado → terminar el loop
            try:
                line = _read_line(conn)
                try:
                    msg = decode_msg(line)  # rechaza type desconocido (p.ej. "execute")
                    response = _handle(msg)
                except IpcProtocolError as e:
                    response = {"error": str(e)}  # NO se actúa
                except Exception as e:  # noqa: BLE001 — nunca tumbar el loop
                    response = {"error": f"invalid message: {e}"}
                conn.sendall(encode_msg(response).encode("utf-8"))
            finally:
                conn.close()
    finally:
        srv.close()
        if os.path.exists(socket_path):
            os.unlink(socket_path)
