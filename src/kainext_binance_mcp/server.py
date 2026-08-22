"""MCP server (spec §4.2a). Read key. Propone al confirmador; NUNCA ejecuta."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Literal, TypeVar

from mcp.server.fastmcp import FastMCP

from kainext_binance_mcp import runtime
from kainext_binance_mcp.config import Settings, load_server_settings
from kainext_binance_mcp.derivatives import get_derivatives as _get_derivatives
from kainext_binance_mcp.errors import client_secrets, run_guarded
from kainext_binance_mcp.guard import assert_read_key_safe
from kainext_binance_mcp.ipc import IpcClient
from kainext_binance_mcp.knowledge import register_knowledge
from kainext_binance_mcp.market import MarketEstimator
from kainext_binance_mcp.marketwide import get_market_structure as _get_market_structure
from kainext_binance_mcp.models import (
    AccountInfo,
    AssetBalance,
    BacktestResult,
    CycleAnalysis,
    DerivativesSnapshot,
    Env,
    IndicatorResult,
    Kline,
    MarketStructure,
    NewsItem,
    OpenOrder,
    OrderProposal,
    OrderStatus,
    OrderType,
    PortfolioReport,
    PriceTicker,
    RiskReport,
    SentimentResult,
    Side,
    Signal,
    Ticker24h,
    TimeInForce,
)
from kainext_binance_mcp.tools import analytics as analytics_tools
from kainext_binance_mcp.tools import marketdata as marketdata_tools
from kainext_binance_mcp.tools import news as news_tools
from kainext_binance_mcp.tools import read as read_tools
from kainext_binance_mcp.tools import signals as signals_tools
from kainext_binance_mcp.tools import write as write_tools

# Enum de estrategias de backtest (capa 2, spec §5). Viaja al schema de la tool.
Strategy = Literal["ema_cross", "rsi_threshold"]

_T = TypeVar("_T")

_INSTRUCTIONS = (
    "Security-first Binance spot server AND an honest crypto analysis consultant. "
    "Ground rules for the client: (1) BEFORE giving any investment analysis or "
    "recommendation, read the resources kb://discipline and kb://research/no-edge and "
    "stay consistent with them — no price predictions, no timing calls, signals are "
    "context not advice, nothing here is financial advice. (2) The server only READS "
    "and PROPOSES; execution requires a separate human-gated confirmer process. "
    "(3) Interpretive tools reference their framework resource in their description — "
    "read it before interpreting. (4) The prompts (portfolio_review, asset_thesis, "
    "market_briefing, risk_check, dca_plan) are the recommended methodologies."
)

mcp = FastMCP("binance", _INSTRUCTIONS)


def bootstrap(env: Mapping[str, str]) -> tuple[Settings, object]:
    """§4.2a: bootstrap compartido (runtime) con read key + guard read-only."""
    return runtime.bootstrap(env, load_settings=load_server_settings,
                             assert_key_safe=assert_read_key_safe)


# Alias local para el wiring de tests (la implementación única vive en runtime).
_make_estimator = runtime.make_estimator


def _register_tools(client: object, ipc: IpcClient, market: MarketEstimator,
                    *, is_testnet: bool) -> None:
    """Registra las 23 tools. Cada @mcp.tool() delega en las funciones ya testeadas
    de tools/read.py, tools/write.py, tools/marketdata.py, tools/news.py y tools/signals.py.
    Las read, las de market data (capa 2) y las de señales (capa 4) reciben `client`; las de
    noticias (capa 3) no reciben client (RSS público); las write reciben `ipc`/`market`/`client`
    según corresponda. El server NUNCA ejecuta; las capas 2, 3 y 4 son 100% read-only."""

    # Contrato de error único (v1.0.0): toda excepción de una tool read-only sale mapeada
    # + scrubbeada como ToolExecutionError (via run_guarded, DENTRO del shim — un decorador
    # rompe la introspección de annotations de FastMCP). Las write mantienen OrderProposal.
    def _g(fn: Callable[[], _T]) -> _T:
        return run_guarded(lambda: client_secrets(client), fn)

    # --- 5 read tools (read key) ---
    @mcp.tool()
    def binance_get_balance() -> list[AssetBalance]:
        """Spot balances with non-zero amounts (free/locked)."""
        return _g(lambda: read_tools.get_balance(client))

    @mcp.tool()
    def binance_get_price(symbol: str) -> PriceTicker:
        """Current price for a symbol (e.g. BTCUSDT)."""
        return _g(lambda: read_tools.get_price(client, symbol))

    @mcp.tool()
    def binance_get_open_orders(symbol: str | None = None) -> list[OpenOrder]:
        """Open orders (all, or for one symbol)."""
        return _g(lambda: read_tools.get_open_orders(client, symbol))

    @mcp.tool()
    def binance_get_order_history(symbol: str, limit: int = 50) -> list[OpenOrder]:
        """Order history for a symbol (limit 1-1000)."""
        return _g(lambda: read_tools.get_order_history(client, symbol, limit))

    @mcp.tool()
    def binance_get_account_info() -> AccountInfo:
        """Account info (canTrade, commissions; key permissions on mainnet only)."""
        return _g(lambda: read_tools.get_account_info(client, is_testnet=is_testnet))

    # --- 4 tools de capa 2: market data + indicadores (read key, 100% read-only) ---
    @mcp.tool()
    def binance_get_klines(symbol: str, interval: str, limit: int = 500,
                           last_n: int | None = None) -> list[Kline]:
        """OHLCV candles for a pair/interval (Decimal values). limit <= 1000.

        `last_n` returns only the newest N candles (keeps context small); None = all
        fetched. `limit` still controls how many candles are fetched."""
        return _g(lambda: marketdata_tools.get_klines(client, symbol, interval, limit,
                                                      last_n=last_n))

    @mcp.tool()
    def binance_get_ticker_24h(symbol: str) -> Ticker24h:
        """Rolling 24h stats (change %, high/low, volume, last price)."""
        return _g(lambda: marketdata_tools.get_ticker_24h(client, symbol))

    @mcp.tool()
    def binance_compute_indicators(symbol: str, interval: str, indicators: list[str],
                                   limit: int = 500, last_n: int = 1) -> IndicatorResult:
        """RSI/MACD/EMA/Bollinger/ATR over the klines (float values, candle-aligned).

        Returns only the newest `last_n` values of each series (default 1 = current value
        only) to keep context small; raise `last_n` to see the recent trend. `limit` still
        controls how many candles feed the computation."""
        return _g(lambda: marketdata_tools.compute_indicators(
            client, symbol, interval, indicators, limit, last_n=last_n))

    @mcp.tool()
    def binance_backtest(symbol: str, interval: str, strategy: Strategy,
                         limit: int = 500) -> BacktestResult:
        """Light NO-LOOKAHEAD backtest of a simple rule (ema_cross/rsi_threshold)."""
        return _g(lambda: marketdata_tools.backtest(client, symbol, interval, strategy, limit))

    # --- 2 tools de capa 3: noticias + sentiment (RSS público, 100% read-only) ---
    # No reciben `client`: leen feeds RSS sin API key. Sentiment es señal cruda (disclaimer).
    @mcp.tool()
    def binance_get_news(asset: str | None = None, sources: list[str] | None = None,
                         limit: int | None = None) -> list[NewsItem]:
        """Crypto news from RSS feeds (CoinDesk, crypto.news), filterable by asset/source."""
        return _g(lambda: news_tools.get_news(asset=asset, sources=sources, limit=limit))

    @mcp.tool()
    def binance_get_sentiment(asset: str, window_hours: int = 24) -> SentimentResult:
        """RAW aggregated sentiment for an asset over a window (lexicon-based, NOT a prediction)."""
        return _g(lambda: news_tools.get_sentiment(asset, window_hours=window_hours))

    # --- 3 tools de capa 4: motor de señales + backtest (read key, 100% read-only) ---
    # Combinan indicadores (capa 2) + sentiment (capa 3) + ATR en una señal transparente.
    # PROPONEN; NUNCA colocan órdenes (eso es capa 1 con gate humano).
    @mcp.tool()
    def binance_generate_signal(symbol: str, interval: str = "1h",
                                threshold: float = 0.15) -> Signal:
        """Transparent composite signal for a pair: direction + score + per-factor rationale
        + ATR risk levels. PROPOSES, never executes; every factor exposes its contribution.
        Note: our own out-of-sample walk-forward found NO robust edge (docs/research/) —
        treat signals as context, not as financial advice."""
        return _g(lambda: signals_tools.generate_signal_tool(client, symbol, interval,
                                                             threshold=threshold))

    @mcp.tool()
    def binance_scan_signals(symbols: list[str], interval: str = "1h") -> list[Signal]:
        """Signals for a watchlist, ranked by score (where to LOOK, not auto-trading)."""
        return _g(lambda: signals_tools.scan_signals(client, symbols, interval))

    @mcp.tool()
    def binance_backtest_signal(symbol: str, interval: str = "1h", limit: int = 500,
                                threshold: float | None = None) -> BacktestResult:
        """Backtests the layer-4 TECHNICAL composite signal on history (read-only, no
        lookahead, sentiment=0). Compare total_return_pct vs buy_hold_return_pct: any edge?"""
        return _g(lambda: signals_tools.binance_backtest_signal(
            client, symbol, interval, limit, threshold=threshold))

    # --- 5 analyst tools: capa 5 (datos) + capa 6 (frameworks) — 100% read-only ---
    @mcp.tool()
    def binance_get_derivatives(symbol: str, funding_limit: int = 8) -> DerivativesSnapshot:
        """Public futures positioning for a pair: mark/index price, current funding rate,
        short funding history, open interest. THE leverage thermometer — interpret with
        the kb://glossary resource (funding, OI). No key permissions needed; on testnet
        this data is synthetic."""
        return _g(lambda: _get_derivatives(client, symbol, funding_limit=funding_limit))

    @mcp.tool()
    def binance_get_market_structure() -> MarketStructure:
        """Whole-market context in one cheap call: Fear & Greed (+week series), BTC
        dominance, total market cap, BTC ATH/drawdown, on-chain fees and hashrate.
        Free public sources; any block may be None if its source is down (see notes).
        Interpret with kb://frameworks/cycle-analysis and kb://glossary."""
        return _g(lambda: _get_market_structure())

    @mcp.tool()
    def binance_analyze_cycle(symbol: str = "BTCUSDT") -> CycleAnalysis:
        """Objective cycle-position inputs: Mayer Multiple (price/200d MA), drawdown from
        ATH (BTC only), distance to the next halving. Interpret with
        kb://frameworks/cycle-analysis — output a PHASE with uncertainty, never a target."""
        return _g(lambda: analytics_tools.analyze_cycle(client, symbol))

    @mcp.tool()
    def binance_analyze_portfolio(cost_basis: dict[str, float] | None = None,
                                  tax_rate: float = 0.0,
                                  cashout_spread: float = 0.0) -> PortfolioReport:
        """Values live balances; concentration; and — if the user provides their cost
        basis per asset (USDT) plus tax_rate/cashout_spread — per-asset PNL and the NET
        break-even (taxes+spread; local-currency effects excluded). No personal data is
        stored: everything is a parameter. Sizing doctrine: kb://discipline."""
        return _g(lambda: analytics_tools.analyze_portfolio(
            client, cost_basis=cost_basis, tax_rate=tax_rate, cashout_spread=cashout_spread))

    @mcp.tool()
    def binance_assess_risk(symbols: list[str] | None = None) -> RiskReport:
        """Realized volatility (30/90d), max drawdown (90d window) and BTC correlation
        per asset — defaults to current non-stable holdings. Rehearse drawdowns BEFORE
        the market does it (kb://discipline rule 2)."""
        return _g(lambda: analytics_tools.assess_risk(client, symbols))

    # --- 4 tools de escritura two-phase (server propone; NUNCA ejecuta) ---
    # Los Literal (Side/OrderType/Env/TimeInForce) viajan al schema de la tool y los
    # re-valida Pydantic en runtime al construir CanonicalOrder (spec §3.3).
    @mcp.tool()
    def binance_spot_order_propose(symbol: str, side: Side, type: OrderType, env: Env,
                                   quantity: Decimal | None = None,
                                   quote_quantity: Decimal | None = None,
                                   price: Decimal | None = None,
                                   time_in_force: TimeInForce | None = None) -> OrderProposal:
        """Proposes a spot order to the confirmer (does NOT execute). Returns intent_id."""
        return write_tools.spot_order_propose(
            ipc=ipc, market=market, symbol=symbol, side=side, type=type, env=env,
            quantity=quantity, quote_quantity=quote_quantity, price=price,
            time_in_force=time_in_force)

    @mcp.tool()
    def binance_spot_order_status(intent_id: str) -> OrderStatus:
        """Polls the outcome of a proposed order (no side effects)."""
        return write_tools.spot_order_status(ipc=ipc, intent_id=intent_id)

    @mcp.tool()
    def binance_cancel_order_propose(symbol: str, order_id: int, env: Env) -> OrderProposal:
        """Proposes canceling an order (re-checks status; does NOT cancel)."""
        return write_tools.cancel_order_propose(
            ipc=ipc, client=client, symbol=symbol, order_id=order_id, env=env)

    @mcp.tool()
    def binance_cancel_order_status(intent_id: str) -> OrderStatus:
        """Polls the outcome of a proposed cancellation (no side effects)."""
        return write_tools.cancel_order_status(ipc=ipc, intent_id=intent_id)


def main() -> None:  # pragma: no cover — arranque puro (proceso real + mcp.run stdio)
    settings, client = bootstrap(os.environ)
    ipc = IpcClient(runtime.SOCKET_PATH)
    market = _make_estimator(client)
    _register_tools(client, ipc, market, is_testnet=settings.is_testnet)
    register_knowledge(mcp)
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
