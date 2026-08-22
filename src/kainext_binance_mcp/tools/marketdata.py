"""Tools read-only de capa 2: market data + indicadores + backtest (spec §2).

100% read-only: usan la read key del client; NO tocan el confirmador ni mueven plata.
Delegan en ``klines``, ``indicators`` y ``backtest`` (módulos ya testeados). Validan los
params de entrada (interval válido, indicadores conocidos, strategy del enum) antes de
pegarle a Binance, para fallar barato y con un mensaje claro.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd

from kainext_binance_mcp import backtest as bt
from kainext_binance_mcp import indicators as ind
from kainext_binance_mcp.klines import VALID_INTERVALS, fetch_klines, klines_to_models
from kainext_binance_mcp.models import (
    BacktestResult,
    IndicatorResult,
    Kline,
    Ticker24h,
    validate_symbol,
)

if TYPE_CHECKING:
    from binance.client import Client

# Indicadores soportados (spec §4). El nombre 'macd'/'bollinger' se expande a varias series.
VALID_INDICATORS: frozenset[str] = frozenset(
    {"rsi", "macd", "ema", "bollinger", "atr"}
)


def get_klines(
    client: "Client", symbol: str, interval: str, limit: int = 500,
    last_n: int | None = None,
) -> list[Kline]:
    """Velas OHLCV de un par/intervalo como modelos ``Kline`` (OHLCV en Decimal).

    ``last_n`` (espejo de compute_indicators) devuelve sólo las últimas N velas para no
    inflar el contexto; None (default) = todas las pedidas por ``limit``."""
    if last_n is not None and last_n < 1:
        raise ValueError("last_n must be >= 1 (or None for all fetched candles)")
    df = fetch_klines(client, validate_symbol(symbol), interval, limit)
    models = klines_to_models(df)
    return models[-last_n:] if last_n is not None else models


def get_ticker_24h(client: "Client", symbol: str) -> Ticker24h:
    """Stats rolling 24h de un par (cambio %, high/low, volumen, último precio)."""
    t = client.get_ticker(symbol=validate_symbol(symbol))
    return Ticker24h(
        symbol=t["symbol"],
        price_change_pct=Decimal(str(t["priceChangePercent"])),
        high=Decimal(str(t["highPrice"])),
        low=Decimal(str(t["lowPrice"])),
        volume=Decimal(str(t["volume"])),
        last=Decimal(str(t["lastPrice"])),
    )


def _series_to_list(s: pd.Series) -> list[float | None]:
    """Convierte una serie de indicador a ``list[float | None]`` (NaN -> None para JSON)."""
    return [None if (v is None or math.isnan(v)) else float(v) for v in s.tolist()]


def compute_indicators(
    client: "Client",
    symbol: str,
    interval: str,
    indicators: list[str],
    limit: int = 500,
    last_n: int | None = None,
    **params: float,
) -> IndicatorResult:
    """Calcula los indicadores pedidos sobre las klines y los devuelve alineados a las velas.

    ``indicators`` ⊆ {rsi, macd, ema, bollinger, atr}. ``params`` opcionales por indicador:
    ``rsi_period`` (14), ``ema_period`` (12), ``macd_fast/slow/signal`` (12/26/9),
    ``bollinger_period`` (20), ``bollinger_k`` (2.0), ``atr_period`` (14). Cada serie viene
    como ``list[float | None]`` (None en el periodo de calentamiento), alineada a las velas.

    ``last_n`` recorta cada serie a sus últimos ``last_n`` valores (cola). ``None`` (default
    de la función) devuelve la serie completa. Útil para no inflar el contexto: con
    ``limit=500`` la respuesta completa son miles de puntos; un cliente LLM normalmente sólo
    necesita el último valor (la tool MCP usa ``last_n=1`` por defecto). ``as_of`` siempre
    refiere a la última vela, recorte o no.
    """
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"invalid interval {interval!r}. Valid: {sorted(VALID_INTERVALS)}"
        )
    if not indicators:
        raise ValueError("at least one indicator is required")
    unknown = [i for i in indicators if i not in VALID_INDICATORS]
    if unknown:
        raise ValueError(
            f"unknown indicator(s): {unknown}. Valid: {sorted(VALID_INDICATORS)}"
        )

    df = fetch_klines(client, validate_symbol(symbol), interval, limit)
    close = df["close"]
    out: dict[str, list[float | None]] = {}

    for name in indicators:
        if name == "rsi":
            out["rsi"] = _series_to_list(ind.rsi(close, n=int(params.get("rsi_period", 14))))
        elif name == "ema":
            out["ema"] = _series_to_list(ind.ema(close, n=int(params.get("ema_period", 12))))
        elif name == "macd":
            macd_line, signal_line, hist = ind.macd(
                close,
                fast=int(params.get("macd_fast", 12)),
                slow=int(params.get("macd_slow", 26)),
                signal=int(params.get("macd_signal", 9)),
            )
            out["macd"] = _series_to_list(macd_line)
            out["macd_signal"] = _series_to_list(signal_line)
            out["macd_hist"] = _series_to_list(hist)
        elif name == "bollinger":
            upper, mid, lower = ind.bollinger(
                close,
                n=int(params.get("bollinger_period", 20)),
                k=float(params.get("bollinger_k", 2.0)),
            )
            out["bollinger_upper"] = _series_to_list(upper)
            out["bollinger_mid"] = _series_to_list(mid)
            out["bollinger_lower"] = _series_to_list(lower)
        else:  # atr
            out["atr"] = _series_to_list(
                ind.atr(df["high"], df["low"], close, n=int(params.get("atr_period", 14)))
            )

    if last_n is not None:
        if last_n < 1:
            raise ValueError("last_n must be >= 1 (or None for the full series)")
        out = {name: series[-last_n:] for name, series in out.items()}

    as_of = int(df["close_time"].iloc[-1]) if len(df) else 0
    return IndicatorResult(symbol=symbol, interval=interval, indicators=out, as_of=as_of)


def backtest(
    client: "Client",
    symbol: str,
    interval: str,
    strategy: str,
    limit: int = 500,
    **params: float,
) -> BacktestResult:
    """Backtest liviano sin lookahead de una estrategia simple sobre históricos (spec §5).

    ``strategy`` ∈ {ema_cross, rsi_threshold}. ``params`` se pasan a la estrategia
    (fast/slow para ema_cross; low/high/n para rsi_threshold).
    """
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"invalid interval {interval!r}. Valid: {sorted(VALID_INTERVALS)}"
        )
    if strategy not in bt.STRATEGIES:
        raise ValueError(
            f"unknown strategy {strategy!r}. Valid: {sorted(bt.STRATEGIES)}"
        )
    df = fetch_klines(client, validate_symbol(symbol), interval, limit)
    return bt.backtest_df(df, symbol, interval, strategy, **params)
