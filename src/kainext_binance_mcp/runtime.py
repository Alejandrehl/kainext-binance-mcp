"""Piezas de runtime compartidas por los DOS procesos (server read-key y confirmador
trade-key). Antes vivían duplicadas en server.py y confirmer/__main__.py con un
comentario "deben coincidir" — ahora coinciden por construcción."""
from __future__ import annotations
import os
from collections.abc import Callable, Mapping
from decimal import Decimal

from kainext_binance_mcp.client import make_client
from kainext_binance_mcp.config import Settings
from kainext_binance_mcp.guard import perms_from_api
from kainext_binance_mcp.market import MarketEstimator, SymbolFilters, parse_symbol_filters
from kainext_binance_mcp.models import KeyPermissions

# Socket del IPC server↔confirmador. ÚNICA definición (ambos procesos la importan).
SOCKET_PATH = os.path.expanduser(
    "~/Library/Application Support/kainext-binance-mcp/confirmer.sock")


def bootstrap(env: Mapping[str, str], *,
              load_settings: Callable[[Mapping[str, str]], Settings],
              assert_key_safe: Callable[[KeyPermissions], None]) -> tuple[Settings, object]:
    """§4.2: valida env → Client + time-offset → test-call → (mainnet) guard de la key.
    El server pasa (load_server_settings, assert_read_key_safe); el confirmador pasa
    (load_confirmer_settings, assert_trade_key_safe)."""
    settings = load_settings(env)
    client = make_client(settings)
    client.get_account()  # test-call firmado
    if not settings.is_testnet:
        assert_key_safe(perms_from_api(client.get_account_api_permissions()))
    return settings, client


def make_estimator(client: object) -> MarketEstimator:
    def get_filters(symbol: str) -> SymbolFilters:
        return parse_symbol_filters(client.get_symbol_info(symbol))  # type: ignore[attr-defined]

    def get_price(symbol: str) -> Decimal:
        return Decimal(client.get_symbol_ticker(symbol=symbol)["price"])  # type: ignore[attr-defined]

    return MarketEstimator(get_filters=get_filters, get_price=get_price)
