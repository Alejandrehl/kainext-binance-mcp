"""MCP server (spec §4.2a). Read key. Propone al confirmador; NUNCA ejecuta."""
from __future__ import annotations
import os
from decimal import Decimal
from typing import Literal, Mapping

from mcp.server.fastmcp import FastMCP

from kainext_binance_mcp.client import make_client
from kainext_binance_mcp.config import Settings, load_server_settings
from kainext_binance_mcp.guard import assert_read_key_safe, perms_from_api
from kainext_binance_mcp.ipc import IpcClient
from kainext_binance_mcp.market import MarketEstimator, SymbolFilters, parse_symbol_filters
from kainext_binance_mcp.models import (
    AccountInfo, AssetBalance, BacktestResult, Env, IndicatorResult, Kline,
    NewsItem, OpenOrder, OrderProposal, OrderStatus, OrderType, PriceTicker,
    SentimentResult, Side, Signal, Ticker24h, TimeInForce,
)
from kainext_binance_mcp.tools import marketdata as marketdata_tools
from kainext_binance_mcp.tools import news as news_tools
from kainext_binance_mcp.tools import read as read_tools
from kainext_binance_mcp.tools import signals as signals_tools
from kainext_binance_mcp.tools import write as write_tools

# Enum de estrategias de backtest (capa 2, spec §5). Viaja al schema de la tool.
Strategy = Literal["ema_cross", "rsi_threshold"]

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
    """Registra las 18 tools. Cada @mcp.tool() delega en las funciones ya testeadas
    de tools/read.py, tools/write.py, tools/marketdata.py, tools/news.py y tools/signals.py.
    Las read, las de market data (capa 2) y las de señales (capa 4) reciben `client`; las de
    noticias (capa 3) no reciben client (RSS público); las write reciben `ipc`/`market`/`client`
    según corresponda. El server NUNCA ejecuta; las capas 2, 3 y 4 son 100% read-only."""

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

    # --- 4 tools de capa 2: market data + indicadores (read key, 100% read-only) ---
    @mcp.tool()
    def binance_get_klines(symbol: str, interval: str, limit: int = 500) -> list[Kline]:
        """Velas OHLCV de un par/intervalo (OHLCV en Decimal). limit ≤ 1000."""
        return marketdata_tools.get_klines(client, symbol, interval, limit)

    @mcp.tool()
    def binance_get_ticker_24h(symbol: str) -> Ticker24h:
        """Stats rolling 24h (cambio %, high/low, volumen, último precio)."""
        return marketdata_tools.get_ticker_24h(client, symbol)

    @mcp.tool()
    def binance_compute_indicators(symbol: str, interval: str, indicators: list[str],
                                   limit: int = 500) -> IndicatorResult:
        """RSI/MACD/EMA/Bollinger/ATR sobre las klines (valores float, alineados a velas)."""
        return marketdata_tools.compute_indicators(client, symbol, interval, indicators, limit)

    @mcp.tool()
    def binance_backtest(symbol: str, interval: str, strategy: Strategy,
                         limit: int = 500) -> BacktestResult:
        """Backtest liviano SIN LOOKAHEAD de una regla simple (ema_cross/rsi_threshold)."""
        return marketdata_tools.backtest(client, symbol, interval, strategy, limit)

    # --- 2 tools de capa 3: noticias + sentiment (RSS público, 100% read-only) ---
    # No reciben `client`: leen feeds RSS sin API key. Sentiment es señal cruda (disclaimer).
    @mcp.tool()
    def binance_get_news(asset: str | None = None, sources: list[str] | None = None,
                         limit: int | None = None) -> list[NewsItem]:
        """Noticias crypto desde RSS (CoinDesk, crypto.news), filtrables por activo/fuente."""
        return news_tools.get_news(asset=asset, sources=sources, limit=limit)

    @mcp.tool()
    def binance_get_sentiment(asset: str, window_hours: int = 24) -> SentimentResult:
        """Sentiment CRUDO agregado de un activo sobre una ventana (léxico, no es predicción)."""
        return news_tools.get_sentiment(asset, window_hours=window_hours)

    # --- 3 tools de capa 4: motor de señales + backtest (read key, 100% read-only) ---
    # Combinan indicadores (capa 2) + sentiment (capa 3) + ATR en una señal transparente.
    # PROPONEN; NUNCA colocan órdenes (eso es capa 1 con gate humano).
    @mcp.tool()
    def binance_generate_signal(symbol: str, interval: str = "1h",
                                threshold: float = 0.15) -> Signal:
        """Señal compuesta y transparente de un par: dirección + score + rationale por factor
        + niveles de riesgo (ATR). PROPONE, no ejecuta; cada factor expone su contribución."""
        return signals_tools.generate_signal_tool(client, symbol, interval, threshold=threshold)

    @mcp.tool()
    def binance_scan_signals(symbols: list[str], interval: str = "1h") -> list[Signal]:
        """Genera señales para una watchlist y las rankea por score (dónde mirar, no auto-operar)."""
        return signals_tools.scan_signals(client, symbols, interval)

    @mcp.tool()
    def binance_backtest_signal(symbol: str, interval: str = "1h", limit: int = 500,
                                threshold: float | None = None) -> BacktestResult:
        """Backtestea la señal TÉCNICA compuesta de capa 4 sobre históricos (read-only, sin
        lookahead, sentiment=0). Compara total_return_pct vs buy_hold_return_pct: ¿hay edge?"""
        return signals_tools.binance_backtest_signal(
            client, symbol, interval, limit, threshold=threshold)

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
