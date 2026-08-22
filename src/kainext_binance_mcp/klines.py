"""Fetch + parseo de klines de Binance a ``pandas.DataFrame`` (spec §4 E4).

``fetch_klines`` valida el ``interval`` contra el set oficial de Binance y hace clamp
del ``limit`` a 1000 (límite de la API). El DataFrame trae OHLCV como ``float64`` (para
alimentar los indicadores) y los tiempos como enteros.

Para no perder precisión en los outputs (E3: OHLCV en Decimal), guardamos las cadenas
crudas de Binance en ``df.attrs["raw_ohlcv"]`` y ``klines_to_models`` reconstruye los
``Decimal`` exactos desde esas cadenas — nunca desde el float (que introduciría artefactos
binarios).
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd

from kainext_binance_mcp.models import Kline

if TYPE_CHECKING:
    from binance.client import Client

# Intervalos válidos de Binance (spec §4 E4).
VALID_INTERVALS: frozenset[str] = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
     "12h", "1d", "3d", "1w", "1M"}
)
MAX_LIMIT = 1000

_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def fetch_klines(
    client: Client, symbol: str, interval: str, limit: int = 500
) -> pd.DataFrame:
    """Trae velas OHLCV y las devuelve como DataFrame con columnas estandarizadas.

    Valida ``interval`` y hace clamp de ``limit`` a [1, 1000].
    """
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"invalid interval {interval!r}. Valid: {sorted(VALID_INTERVALS)}"
        )
    capped = max(1, min(int(limit), MAX_LIMIT))
    raw: list[list[Any]] = client.get_klines(symbol=symbol, interval=interval, limit=capped)

    return _raw_to_df(raw)


def klines_to_models(df: pd.DataFrame) -> list[Kline]:
    """Convierte el DataFrame de ``fetch_klines`` a ``list[Kline]`` con OHLCV en Decimal (E3).

    Usa las cadenas crudas de ``df.attrs["raw_ohlcv"]`` cuando están disponibles para
    preservar la precisión exacta; si no, cae a ``Decimal(str(float))`` como respaldo.
    """
    raw_ohlcv: list[dict[str, str]] | None = df.attrs.get("raw_ohlcv")
    out: list[Kline] = []
    for i, (_, row) in enumerate(df.iterrows()):
        if raw_ohlcv is not None:
            r = raw_ohlcv[i]
            o, h, low_, c, v = (
                Decimal(r["open"]), Decimal(r["high"]), Decimal(r["low"]),
                Decimal(r["close"]), Decimal(r["volume"]),
            )
        else:
            o, h, low_, c, v = (
                Decimal(str(row["open"])), Decimal(str(row["high"])),
                Decimal(str(row["low"])), Decimal(str(row["close"])),
                Decimal(str(row["volume"])),
            )
        out.append(
            Kline(
                open_time=int(row["open_time"]),
                open=o, high=h, low=low_, close=c, volume=v,
                close_time=int(row["close_time"]),
            )
        )
    return out


def _raw_to_df(raw: list[list[Any]]) -> pd.DataFrame:
    open_time = [int(r[0]) for r in raw]
    close_time = [int(r[6]) for r in raw]
    # Cadenas crudas para reconstruir Decimals exactos en klines_to_models.
    raw_ohlcv = [
        {"open": str(r[1]), "high": str(r[2]), "low": str(r[3]),
         "close": str(r[4]), "volume": str(r[5])}
        for r in raw
    ]
    df = pd.DataFrame(
        {
            "open_time": pd.Series(open_time, dtype="int64"),
            "open": pd.Series([float(r[1]) for r in raw], dtype="float64"),
            "high": pd.Series([float(r[2]) for r in raw], dtype="float64"),
            "low": pd.Series([float(r[3]) for r in raw], dtype="float64"),
            "close": pd.Series([float(r[4]) for r in raw], dtype="float64"),
            "volume": pd.Series([float(r[5]) for r in raw], dtype="float64"),
            "close_time": pd.Series(close_time, dtype="int64"),
        },
        columns=_COLUMNS,
    )
    df.attrs["raw_ohlcv"] = raw_ohlcv
    return df


def fetch_klines_range(client: Client, symbol: str, interval: str,
                       start_ms: int, end_ms: int) -> pd.DataFrame:
    """Velas de un RANGO temporal, paginando sobre el cap de 1000 de la API.

    Necesario para backtests multianuales (la historia diaria de BTCUSDT parte el
    2017-08-17). Devuelve el mismo DataFrame estandarizado de ``fetch_klines``."""
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"invalid interval {interval!r}. Valid: {sorted(VALID_INTERVALS)}"
        )
    if start_ms >= end_ms:
        raise ValueError("start_ms must be < end_ms")
    chunks: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        raw: list[list[Any]] = client.get_klines(
            symbol=symbol, interval=interval, startTime=cursor, endTime=end_ms,
            limit=MAX_LIMIT)
        if not raw:
            break
        chunks.extend(raw)
        last_close = int(raw[-1][6])
        if len(raw) < MAX_LIMIT or last_close >= end_ms:
            break
        cursor = last_close + 1
    return _raw_to_df(chunks)
