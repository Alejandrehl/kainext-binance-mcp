"""Confirmador (spec §4.2b/§4.3). Trade key. Único que ejecuta, sólo tras el clic."""
from __future__ import annotations
import os
import secrets
import threading
import time
from decimal import Decimal
from typing import Mapping

from kainext_binance_mcp.client import make_client
from kainext_binance_mcp.config import Settings, load_confirmer_settings
from kainext_binance_mcp.guard import assert_trade_key_safe, perms_from_api
from kainext_binance_mcp.intents import IntentStore
from kainext_binance_mcp.ipc import serve
from kainext_binance_mcp.market import MarketEstimator, SymbolFilters, parse_symbol_filters

SOCKET_PATH = os.path.expanduser(
    "~/Library/Application Support/kainext-binance-mcp/confirmer.sock")


def bootstrap(env: Mapping[str, str]) -> tuple[Settings, object]:
    """§4.2b: valida env (mismo BINANCE_ENV) → Client trade + time-offset → test-call
    → (mainnet) guard de la trade key (§4.4); abort si la key es insegura."""
    settings = load_confirmer_settings(env)
    client = make_client(settings)
    client.get_account()  # test-call firmado
    if not settings.is_testnet:
        assert_trade_key_safe(perms_from_api(client.get_account_api_permissions()))
    return settings, client


def _make_estimator(client: object) -> MarketEstimator:
    def get_filters(symbol: str) -> SymbolFilters:
        return parse_symbol_filters(client.get_symbol_info(symbol))  # type: ignore[attr-defined]

    def get_price(symbol: str) -> Decimal:
        return Decimal(client.get_symbol_ticker(symbol=symbol)["price"])  # type: ignore[attr-defined]

    return MarketEstimator(get_filters=get_filters, get_price=get_price)


def main() -> None:  # pragma: no cover — arranque puro (proceso real + serve() bloqueante)
    _settings, client = bootstrap(os.environ)
    nonce = secrets.token_hex(16)               # secreto del confirmador (no expuesto al modelo)
    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    dialog_lock = threading.Lock()              # anti-spam: un diálogo a la vez (§4.3c)
    estimator = _make_estimator(client)         # la trade key puede leer (filtros/precio)
    serve(SOCKET_PATH, store, client, nonce, dialog_lock, estimator)


if __name__ == "__main__":  # pragma: no cover
    main()
