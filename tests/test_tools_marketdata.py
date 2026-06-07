"""Tests de las 4 tools read-only de capa 2 (plan Task 5, spec §2) con client mockeado."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kainext_binance_mcp.models import (
    BacktestResult,
    IndicatorResult,
    Kline,
    Ticker24h,
)
from kainext_binance_mcp.tools import marketdata as md


def _binance_klines(n: int = 40) -> list[list[object]]:
    rows: list[list[object]] = []
    base = 1717000000000
    for i in range(n):
        price = 100.0 + i  # tendencia alcista
        rows.append(
            [
                base + i * 3600000,
                f"{price:.2f}", f"{price + 1:.2f}", f"{price - 1:.2f}",
                f"{price + 0.5:.2f}", "10.0",
                base + i * 3600000 + 3599999,
                "1000.0", 50, "5.0", "500.0", "0",
            ]
        )
    return rows


# --------------------------------------------------------------------------- #
# get_klines
# --------------------------------------------------------------------------- #

def test_get_klines_returns_models() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_klines(3)
    out = md.get_klines(c, "BTCUSDT", "1h", 3)
    assert isinstance(out, list)
    assert len(out) == 3
    assert all(isinstance(k, Kline) for k in out)
    assert isinstance(out[0].open, Decimal)


def test_get_klines_invalid_interval_raises() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="interval"):
        md.get_klines(c, "BTCUSDT", "13h", 3)
    c.get_klines.assert_not_called()


# --------------------------------------------------------------------------- #
# get_ticker_24h
# --------------------------------------------------------------------------- #

def test_get_ticker_24h() -> None:
    c = MagicMock()
    c.get_ticker.return_value = {
        "symbol": "BTCUSDT",
        "priceChangePercent": "2.5",
        "highPrice": "51000.0",
        "lowPrice": "49000.0",
        "volume": "1234.5",
        "lastPrice": "50500.0",
    }
    t = md.get_ticker_24h(c, "BTCUSDT")
    assert isinstance(t, Ticker24h)
    assert t.symbol == "BTCUSDT"
    assert t.price_change_pct == Decimal("2.5")
    assert t.high == Decimal("51000.0")
    assert t.low == Decimal("49000.0")
    assert t.volume == Decimal("1234.5")
    assert t.last == Decimal("50500.0")
    c.get_ticker.assert_called_once_with(symbol="BTCUSDT")


# --------------------------------------------------------------------------- #
# compute_indicators
# --------------------------------------------------------------------------- #

def test_compute_indicators_returns_requested_series() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_klines(40)
    res = md.compute_indicators(
        c, "BTCUSDT", "1h", ["rsi", "macd", "ema", "bollinger", "atr"], limit=40
    )
    assert isinstance(res, IndicatorResult)
    assert res.symbol == "BTCUSDT"
    assert res.interval == "1h"
    # RSI
    assert "rsi" in res.indicators
    assert len(res.indicators["rsi"]) == 40
    # MACD se expande a tres series.
    assert {"macd", "macd_signal", "macd_hist"} <= set(res.indicators)
    # EMA
    assert "ema" in res.indicators
    # Bollinger se expande a tres bandas.
    assert {"bollinger_upper", "bollinger_mid", "bollinger_lower"} <= set(res.indicators)
    # ATR
    assert "atr" in res.indicators
    # as_of = close_time de la última vela.
    assert res.as_of == _binance_klines(40)[-1][6]
    # Warmup => None al inicio de RSI.
    assert res.indicators["rsi"][0] is None
    # RSI numérico en rango.
    last_rsi = res.indicators["rsi"][-1]
    assert last_rsi is not None and 0.0 <= last_rsi <= 100.0


def test_compute_indicators_with_params() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_klines(40)
    res = md.compute_indicators(c, "BTCUSDT", "1h", ["ema"], limit=40, ema_period=5)
    assert "ema" in res.indicators
    assert len(res.indicators["ema"]) == 40


def test_compute_indicators_unknown_indicator_raises() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_klines(40)
    with pytest.raises(ValueError, match="indicador"):
        md.compute_indicators(c, "BTCUSDT", "1h", ["stoch"], limit=40)


def test_compute_indicators_empty_list_raises() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="al menos un indicador"):
        md.compute_indicators(c, "BTCUSDT", "1h", [], limit=40)


def test_compute_indicators_invalid_interval_raises() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="interval"):
        md.compute_indicators(c, "BTCUSDT", "99h", ["rsi"], limit=40)
    c.get_klines.assert_not_called()


# --------------------------------------------------------------------------- #
# backtest
# --------------------------------------------------------------------------- #

def test_backtest_returns_result() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_klines(60)
    res = md.backtest(c, "BTCUSDT", "1h", "ema_cross", limit=60, fast=3, slow=8)
    assert isinstance(res, BacktestResult)
    assert res.symbol == "BTCUSDT"
    assert res.strategy == "ema_cross"
    assert res.disclaimer


def test_backtest_unknown_strategy_raises() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="strategy"):
        md.backtest(c, "BTCUSDT", "1h", "martingale", limit=60)
    c.get_klines.assert_not_called()


def test_backtest_invalid_interval_raises() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="interval"):
        md.backtest(c, "BTCUSDT", "100h", "ema_cross", limit=60)
    c.get_klines.assert_not_called()


def test_backtest_rsi_threshold() -> None:
    c = MagicMock()
    c.get_klines.return_value = _binance_klines(60)
    res = md.backtest(
        c, "BTCUSDT", "1h", "rsi_threshold", limit=60, low=30.0, high=70.0
    )
    assert res.strategy == "rsi_threshold"
