"""MCP server (spec §4.2a). Read key. Propone al confirmador; NUNCA ejecuta."""
from __future__ import annotations
import os
from decimal import Decimal
from typing import Mapping

from mcp.server.fastmcp import FastMCP

from kainext_binance_mcp.client import make_client
from kainext_binance_mcp.config import Settings, load_server_settings
from kainext_binance_mcp.guard import assert_read_key_safe, perms_from_api
from kainext_binance_mcp.ipc import IpcClient
from kainext_binance_mcp.market import MarketEstimator, SymbolFilters, parse_symbol_filters
from kainext_binance_mcp.models import (
    AccountInfo, AssetBalance, Env, OpenOrder, OrderProposal, OrderStatus,
    OrderType, PriceTicker, Side, TimeInForce,
)
from kainext_binance_mcp.tools import read as read_tools
from kainext_binance_mcp.tools import write as write_tools

mcp = FastMCP("binance")

# Socket del confirmador (debe coincidir con kainext_binance_mcp_confirmer.__main__.SOCKET_PATH).
SOCKET_PATH = os.path.expanduser(
    "~/Library/Application Support/kainext-binance-mcp/confirmer.sock")


def bootstrap(env: Mapping[str, str]) -> tuple[Settings, object]:
    """§4.2a: valida env → Client read + time-offset → test-call → (mainnet) guard
    read-only (abort si la read key puede tradear)."""
    settings = load_server_settings(env)
    client = make_client(settings)
    client.get_account()  # test-call firmado
    if not settings.is_testnet:
        assert_read_key_safe(perms_from_api(client.get_account_api_permissions()))
    return settings, client


def _make_estimator(client: object) -> MarketEstimator:
    def get_filters(symbol: str) -> SymbolFilters:
        return parse_symbol_filters(client.get_symbol_info(symbol))  # type: ignore[attr-defined]

    def get_price(symbol: str) -> Decimal:
        return Decimal(client.get_symbol_ticker(symbol=symbol)["price"])  # type: ignore[attr-defined]

    return MarketEstimator(get_filters=get_filters, get_price=get_price)


def _register_tools(client: object, ipc: IpcClient, market: MarketEstimator,
                    *, is_testnet: bool) -> None:
    """Registra las 9 tools. Cada @mcp.tool() delega en las funciones ya testeadas
    de tools/read.py y tools/write.py. Las read reciben `client`; las write reciben
    `ipc`/`market`/`client` según corresponda. El server NUNCA ejecuta."""

    # --- 5 tools de lectura (read key) ---
    @mcp.tool()
    def binance_get_balance() -> list[AssetBalance]:
        """Balances spot con saldo distinto de cero (free/locked)."""
        return read_tools.get_balance(client)

    @mcp.tool()
    def binance_get_price(symbol: str) -> PriceTicker:
        """Precio actual de un símbolo (ej. BTCUSDT)."""
        return read_tools.get_price(client, symbol)

    @mcp.tool()
    def binance_get_open_orders(symbol: str | None = None) -> list[OpenOrder]:
        """Órdenes abiertas (todas o de un símbolo)."""
        return read_tools.get_open_orders(client, symbol)

    @mcp.tool()
    def binance_get_order_history(symbol: str, limit: int = 50) -> list[OpenOrder]:
        """Historial de órdenes de un símbolo."""
        return read_tools.get_order_history(client, symbol, limit)

    @mcp.tool()
    def binance_get_account_info() -> AccountInfo:
        """Info de cuenta (canTrade, comisiones; permisos de key sólo en mainnet)."""
        return read_tools.get_account_info(client, is_testnet=is_testnet)

    # --- 4 tools de escritura two-phase (server propone; NUNCA ejecuta) ---
    # Los Literal (Side/OrderType/Env/TimeInForce) viajan al schema de la tool y los
    # re-valida Pydantic en runtime al construir CanonicalOrder (spec §3.3).
    @mcp.tool()
    def binance_spot_order_propose(symbol: str, side: Side, type: OrderType, env: Env,
                                   quantity: Decimal | None = None,
                                   quote_quantity: Decimal | None = None,
                                   price: Decimal | None = None,
                                   time_in_force: TimeInForce | None = None) -> OrderProposal:
        """Propone una orden spot al confirmador (no ejecuta). Devuelve intent_id."""
        return write_tools.spot_order_propose(
            ipc=ipc, market=market, symbol=symbol, side=side, type=type, env=env,
            quantity=quantity, quote_quantity=quote_quantity, price=price,
            time_in_force=time_in_force)

    @mcp.tool()
    def binance_spot_order_status(intent_id: str) -> OrderStatus:
        """Consulta el desenlace de una orden propuesta (sin efecto)."""
        return write_tools.spot_order_status(ipc=ipc, intent_id=intent_id)

    @mcp.tool()
    def binance_cancel_order_propose(symbol: str, order_id: int, env: Env) -> OrderProposal:
        """Propone cancelar una orden (re-consulta estado; no cancela)."""
        return write_tools.cancel_order_propose(
            ipc=ipc, client=client, symbol=symbol, order_id=order_id, env=env)

    @mcp.tool()
    def binance_cancel_order_status(intent_id: str) -> OrderStatus:
        """Consulta el desenlace de una cancelación propuesta (sin efecto)."""
        return write_tools.cancel_order_status(ipc=ipc, intent_id=intent_id)


def main() -> None:  # pragma: no cover — arranque puro (proceso real + mcp.run stdio)
    settings, client = bootstrap(os.environ)
    ipc = IpcClient(SOCKET_PATH)
    market = _make_estimator(client)
    _register_tools(client, ipc, market, is_testnet=settings.is_testnet)
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
