"""Protocolo IPC server↔confirmador (spec §4.3b). JSON line-delimited.
Sólo 'register' y 'status'. NO existe 'execute'/'approve': la ejecución
sólo nace del clic en el diálogo del confirmador."""
from __future__ import annotations
import json
from typing import Any

PROTOCOL_VERSION = 1
_ALLOWED_TYPES = {"register", "status"}


class IpcProtocolError(Exception):
    pass


def encode_msg(msg: dict[str, Any]) -> str:
    return json.dumps(msg, separators=(",", ":")) + "\n"


def decode_msg(line: str) -> dict[str, Any]:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        raise IpcProtocolError(f"JSON inválido: {e}") from e
    if not isinstance(msg, dict):
        raise IpcProtocolError("mensaje no es objeto")
    if msg.get("v") != PROTOCOL_VERSION:
        raise IpcProtocolError(f"versión de protocolo no soportada: {msg.get('v')}")
    if msg.get("type") not in _ALLOWED_TYPES:
        raise IpcProtocolError(f"type no permitido: {msg.get('type')}")
    return msg
