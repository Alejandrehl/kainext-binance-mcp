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

import pandas as pd

from kainext_binance_mcp import indicators as ind
from kainext_binance_mcp.klines import VALID_INTERVALS, fetch_klines
from kainext_binance_mcp.models import SentimentResult, Signal
from kainext_binance_mcp.signals import engine
from kainext_binance_mcp.tools import news as news_tools

if TYPE_CHECKING:
    from binance.client import Client

# Knobs por defecto de los indicadores (alineados con capa 2 / spec §4).
_EMA_FAST = 12
_EMA_SLOW = 26
_RSI_PERIOD = 14
_BOLL_PERIOD = 20
_BOLL_K = 2.0
_ATR_PERIOD = 14
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


def _last_valid(series: pd.Series, default: float = 0.0) -> float:
    """Último valor no-NaN de una serie de indicador (el del cierre más reciente utilizable).

    Devuelve ``default`` si toda la serie es NaN (no debería pasar con _LIMIT velas, pero es
    honesto y no rompe la señal: un factor sin dato calculable queda en su neutro). El neutro
    depende del indicador — 0.0 para EMA/MACD/ATR, 50.0 para RSI, por eso es parametrizable.
    """
    s = series.dropna()
    if s.empty:
        return default
    return float(s.iloc[-1])


def _bb_position(price: float, lower: float, upper: float) -> float:
    """Posición %B del precio dentro de las bandas de Bollinger: 0 = inferior, 1 = superior.

    Si las bandas colapsan (upper == lower, serie plana) devuelve 0.5 (neutro: sin señal).
    """
    width = upper - lower
    if width <= 0.0:
        return 0.5
    return (price - lower) / width


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
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"interval inválido: {interval!r}. Válidos: {sorted(VALID_INTERVALS)}"
        )
    sentiment_fn = _sentiment_fn if _sentiment_fn is not None else news_tools.get_sentiment

    df = fetch_klines(client, symbol, interval, _LIMIT)
    close = df["close"]

    ema_fast = _last_valid(ind.ema(close, _EMA_FAST))
    ema_slow = _last_valid(ind.ema(close, _EMA_SLOW))
    rsi = _last_valid(ind.rsi(close, _RSI_PERIOD), default=50.0)  # sin RSI → momentum neutro
    _macd_line, _signal_line, hist = ind.macd(close)
    macd_hist = _last_valid(hist)
    upper, _mid, lower = ind.bollinger(close, _BOLL_PERIOD, _BOLL_K)
    atr_val = _last_valid(ind.atr(df["high"], df["low"], close, _ATR_PERIOD))

    last_price_float = float(close.iloc[-1])
    bb_pos = _bb_position(last_price_float, _last_valid(lower), _last_valid(upper))

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
