"""Tools read-only de capa 4: generate_signal + scan_signals (spec §2/§6).

100% read-only / PROPONE: arman los inputs del engine desde capa 2 (klines → EMA fast/slow,
RSI, MACD hist, posición Bollinger, ATR) y capa 3 (sentiment crudo del activo), y delegan en
el engine PURO ``signals.engine.generate_signal``. NO tocan el confirmador ni mueven plata;
toda ejecución es capa 1 con gate humano (spec S1).

``scan_signals`` corre ``generate_signal_tool`` sobre una watchlist y rankea por score
descendente — para elegir dónde mirar, no para auto-operar (spec S7).

El parámetro ``_sentiment_fn`` es inyectable para testear sin red; en producción usa el
default real (``news.tools.get_sentiment``). Si la capa 3 falla (red caída), el sentiment se
degrada a 0.0: la señal técnica sigue siendo válida.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Callable


from kainext_binance_mcp import indicators as ind
from kainext_binance_mcp.backtest import COMMISSION_TAKER
from kainext_binance_mcp.klines import VALID_INTERVALS, fetch_klines
from kainext_binance_mcp.models import BacktestResult, SentimentResult, Signal, validate_symbol
from kainext_binance_mcp.signals import common, engine
from kainext_binance_mcp.signals.backtest_signal import backtest_signal
from kainext_binance_mcp.tools import news as news_tools

if TYPE_CHECKING:
    from binance.client import Client

# Knobs de indicadores: en signals/common.py (compartidos con el backtest de la señal).
_LIMIT = 200  # suficiente para el calentamiento de EMA26/MACD/Bollinger/ATR.

# Quote assets conocidos de Binance: para derivar el activo base del símbolo (BTCUSDT → BTC)
# y pedir el sentiment de ese activo (capa 3). Más largos primero para no cortar de menos.
_QUOTE_ASSETS: tuple[str, ...] = (
    "USDT", "FDUSD", "TUSD", "USDC", "BUSD", "DAI", "BTC", "ETH", "BNB", "EUR", "TRY", "BRL",
)

SentimentFn = Callable[..., SentimentResult]


def _base_asset(symbol: str) -> str:
    """Deriva el activo base de un símbolo spot (BTCUSDT → BTC, ETHBTC → ETH).

    Hace strip del primer quote asset conocido que sea sufijo; si ninguno aplica, devuelve el
    símbolo completo (mejor pedir sentiment de algo que de nada).
    """
    up = symbol.upper()
    for quote in _QUOTE_ASSETS:
        if up.endswith(quote) and len(up) > len(quote):
            return up[: -len(quote)]
    return up


def generate_signal_tool(
    client: "Client",
    symbol: str,
    interval: str = "1h",
    *,
    weights: dict[str, float] | None = None,
    threshold: float = engine.DEFAULT_THRESHOLD,
    atr_mult: float = engine.DEFAULT_ATR_MULT,
    rr: float = engine.DEFAULT_RR,
    window_hours: int = 24,
    _sentiment_fn: SentimentFn | None = None,
) -> Signal:
    """Señal compuesta para un par: arma inputs de capa 2/3 y llama al engine puro (spec §2).

    Calcula sobre las klines: EMA(12)/EMA(26) (tendencia), RSI(14) (momentum), histograma
    MACD, posición en Bollinger(20,2) y ATR(14); trae el sentiment crudo del activo base
    (capa 3, degradado a 0.0 si la red falla). Read-only — PROPONE, nunca ejecuta (S1).
    """
    validate_symbol(symbol)
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"invalid interval {interval!r}. Valid: {sorted(VALID_INTERVALS)}"
        )
    sentiment_fn = _sentiment_fn if _sentiment_fn is not None else news_tools.get_sentiment

    df = fetch_klines(client, symbol, interval, _LIMIT)
    close = df["close"]

    ema_fast = common.last_valid(ind.ema(close, common.EMA_FAST))
    ema_slow = common.last_valid(ind.ema(close, common.EMA_SLOW))
    rsi = common.last_valid(ind.rsi(close, common.RSI_PERIOD), default=50.0)  # sin RSI → momentum neutro
    _macd_line, _signal_line, hist = ind.macd(close)
    macd_hist = common.last_valid(hist)
    upper, _mid, lower = ind.bollinger(close, common.BOLL_PERIOD, common.BOLL_K)
    atr_val = common.last_valid(ind.atr(df["high"], df["low"], close, common.ATR_PERIOD))

    last_price_float = float(close.iloc[-1])
    bb_pos = common.bb_position(last_price_float, common.last_valid(lower), common.last_valid(upper))

    # Precio exacto en Decimal desde la cadena cruda de Binance (sin artefactos binarios).
    raw_ohlcv = df.attrs.get("raw_ohlcv")
    price = (
        Decimal(raw_ohlcv[-1]["close"])
        if raw_ohlcv
        else Decimal(str(last_price_float))
    )
    as_of = int(df["close_time"].iloc[-1]) if len(df) else 0

    # Sentiment del activo base (capa 3). Degrada a 0.0 si la capa 3 falla (red).
    try:
        sentiment = sentiment_fn(_base_asset(symbol), window_hours=window_hours).score
    except Exception:
        sentiment = 0.0

    return engine.generate_signal(
        symbol=symbol,
        interval=interval,
        price=price,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi=rsi,
        macd_hist=macd_hist,
        bb_pos=bb_pos,
        sentiment=sentiment,
        atr=atr_val,
        weights=weights,
        threshold=threshold,
        atr_mult=atr_mult,
        rr=rr,
        as_of=as_of,
    )


def binance_backtest_signal(
    client: "Client",
    symbol: str,
    interval: str = "1h",
    limit: int = 500,
    *,
    weights: dict[str, float] | None = None,
    threshold: float | None = None,
    commission: float = COMMISSION_TAKER,
) -> BacktestResult:
    """Backtest de la señal técnica compuesta de capa 4 sobre históricos (100% read-only).

    Trae las klines (capa 2) y delega en ``signals.backtest_signal``: corre el engine de
    capa 4 por vela con ``sentiment=0`` (no hay sentiment histórico por vela) y reúsa el
    harness anti-lookahead de capa 2. Devuelve un ``BacktestResult`` cuyo ``disclaimer`` deja
    EXPLÍCITO que sólo mide la parte técnica. Comparar ``total_return_pct`` vs
    ``buy_hold_return_pct`` es el test honesto de "¿la señal tiene edge?".
    """
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"invalid interval {interval!r}. Valid: {sorted(VALID_INTERVALS)}"
        )
    df = fetch_klines(client, symbol, interval, limit)
    return backtest_signal(
        df,
        weights=weights,
        threshold=threshold,
        commission=commission,
        symbol=symbol,
        interval=interval,
    )


def scan_signals(
    client: "Client",
    symbols: list[str],
    interval: str = "1h",
    *,
    weights: dict[str, float] | None = None,
    threshold: float = engine.DEFAULT_THRESHOLD,
    atr_mult: float = engine.DEFAULT_ATR_MULT,
    rr: float = engine.DEFAULT_RR,
    window_hours: int = 24,
    _sentiment_fn: SentimentFn | None = None,
) -> list[Signal]:
    """Genera señales para una watchlist y las rankea por score descendente (spec §2/S7).

    Para elegir dónde mirar — NO para auto-operar. Read-only.
    """
    out = [
        generate_signal_tool(
            client, symbol, interval,
            weights=weights, threshold=threshold, atr_mult=atr_mult, rr=rr,
            window_hours=window_hours, _sentiment_fn=_sentiment_fn,
        )
        for symbol in symbols
    ]
    out.sort(key=lambda s: s.score, reverse=True)
    return out
