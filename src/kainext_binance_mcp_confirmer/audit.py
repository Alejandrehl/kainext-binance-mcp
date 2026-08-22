"""Audit log de órdenes ejecutadas (spec §4.10).

Cada orden ejecutada appendea UNA línea JSON a un archivo de auditoría local
(`~/Library/Application Support/kainext-binance-mcp/audit.log`, archivo 0600 en
carpeta 0700). Registra QUÉ se ejecutó —timestamp, ids, símbolo, lado, cantidad
efectiva, precio, env— y NUNCA secretos (ni API key/secret, ni nonce).
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

DEFAULT_AUDIT_PATH = os.path.expanduser(
    "~/Library/Application Support/kainext-binance-mcp/audit.log")


def _json_default(o: Any) -> str:
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"no serializable: {type(o)!r}")


def append_audit_entry(
    *,
    path: str,
    intent_id: str,
    client_order_id: str,
    order_id: int,
    symbol: str,
    side: str,
    effective_qty: Decimal | str | None,
    price: Decimal | str | None,
    env: str,
    action: str = "ORDER",
    executed_qty: Decimal | str | None = None,
) -> None:
    """Appendea una línea JSON al audit log. Crea la carpeta (0700) y el archivo (0600)
    si no existen. SIN secretos. El timestamp es UTC ISO-8601 (instante de la escritura).
    `action` distingue una colocación ('ORDER') de una cancelación ('CANCEL')."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "intent_id": intent_id,
        "action": action,
        "client_order_id": client_order_id,
        "order_id": order_id,
        "symbol": symbol,
        "side": side,
        "effective_qty": effective_qty,
        "executed_qty": executed_qty,
        "price": price,
        "env": env,
    }
    line = json.dumps(entry, separators=(",", ":"), default=_json_default) + "\n"
    # O_APPEND atómico por línea; 0600 al crear (el umask podría relajarlo → chmod explícito).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
