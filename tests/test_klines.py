"""Tests de klines.py con client mockeado (plan Task 2, spec §4 E4).

Formato Binance de klines = lista de listas:
[openTime, open, high, low, close, volume, closeTime, quoteVol, trades, takerBase, takerQuote, ignore]
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

from kainext_binance_mcp.klines import fetch_klines, klines_to_models
from kainext_binance_mcp.models import Kline


def _binance_rows() -> list[list[object]]:
    return [
        [1717000000000, "100.0", "101.0", "99.5", "100.5", "12.5",
         1717003599999, "1256.0", 42, "6.0", "603.0", "0"],
        [1717003600000, "100.5", "102.0", "100.0", "101.5", "20.0",
         1717007199999, "2030.0", 55, "10.0", "1015.0", "0"],
        [1717007200000, "101.5", "103.0", "101.0", "102.0", "18.0",
         1717010799999, "1836.0", 60, "9.0", "918.0", "0"],
    ]


def test_fetch_klines_returns_dataframe_with_columns() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_rows()
    df = fetch_klines(c, "BTCUSDT", "1h", 3)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == [
        "open_time", "open", "high", "low", "close", "volume", "close_time",
    ]
    assert len(df) == 3
    c.get_klines.assert_called_once_with(symbol="BTCUSDT", interval="1h", limit=3)


def test_fetch_klines_numeric_types() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_rows()
    df = fetch_klines(c, "BTCUSDT", "1h", 3)
    # OHLCV numéricos (float para cálculo); tiempos enteros.
    assert df["open"].dtype == "float64"
    assert df["close"].dtype == "float64"
    assert df["volume"].dtype == "float64"
    assert str(df["open_time"].dtype).startswith("int")
    assert df["close"].iloc[-1] == 102.0


def test_fetch_klines_invalid_interval_raises() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="interval"):
        fetch_klines(c, "BTCUSDT", "7h", 3)
    c.get_klines.assert_not_called()


def test_fetch_klines_clamps_limit_to_1000() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_rows()
    fetch_klines(c, "BTCUSDT", "1h", 5000)
    c.get_klines.assert_called_once_with(symbol="BTCUSDT", interval="1h", limit=1000)


def test_fetch_klines_default_limit_500() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_rows()
    fetch_klines(c, "BTCUSDT", "1h")
    c.get_klines.assert_called_once_with(symbol="BTCUSDT", interval="1h", limit=500)


def test_klines_to_models_decimal_ohlcv() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_rows()
    df = fetch_klines(c, "BTCUSDT", "1h", 3)
    models = klines_to_models(df)
    assert isinstance(models, list)
    assert len(models) == 3
    assert all(isinstance(m, Kline) for m in models)
    first = models[0]
    assert first.open == Decimal("100.0")
    assert first.high == Decimal("101.0")
    assert first.open_time == 1717000000000
    assert first.close_time == 1717003599999
    assert isinstance(first.volume, Decimal)
