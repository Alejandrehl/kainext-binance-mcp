"""Confirmador (spec §4.2b/§4.3). Trade key. Único que ejecuta, sólo tras el clic."""
from __future__ import annotations
import os
import secrets
import threading
import time
from typing import Mapping

from kainext_binance_mcp import runtime
from kainext_binance_mcp.config import Settings, load_confirmer_settings
from kainext_binance_mcp.guard import assert_trade_key_safe
from kainext_binance_mcp.intents import IntentStore
from kainext_binance_mcp.ipc import serve

SOCKET_PATH = runtime.SOCKET_PATH  # única definición (runtime); alias para tests/uso local
AUDIT_PATH = os.path.expanduser(
    "~/Library/Application Support/kainext-binance-mcp/audit.log")


def bootstrap(env: Mapping[str, str]) -> tuple[Settings, object]:
    """§4.2b: bootstrap compartido (runtime) con trade key + guard §4.4."""
    return runtime.bootstrap(env, load_settings=load_confirmer_settings,
                             assert_key_safe=assert_trade_key_safe)


# Alias local para el wiring de tests (la implementación única vive en runtime).
_make_estimator = runtime.make_estimator


def main() -> None:  # pragma: no cover — arranque puro (proceso real + serve() bloqueante)
    settings, client = bootstrap(os.environ)
    nonce = secrets.token_hex(16)               # secreto del confirmador (no expuesto al modelo)
    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    dialog_lock = threading.Lock()              # anti-spam: un diálogo a la vez (§4.3c)
    estimator = _make_estimator(client)         # la trade key puede leer (filtros/precio)
    # C3: el confirmador conoce SU propio env; valida que el intent coincida antes de ejecutar.
    # A1: ruta del audit log de órdenes ejecutadas.
    serve(SOCKET_PATH, store, client, nonce, dialog_lock, estimator,
          confirmer_env=settings.env, audit_path=AUDIT_PATH)


if __name__ == "__main__":  # pragma: no cover
    main()
