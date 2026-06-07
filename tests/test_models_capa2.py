"""Tests de construcción de los modelos de capa 2 (plan Task 3, spec §3).

OHLCV/precios en Decimal (E3 consistencia con capa 1); valores de indicadores en float.
"""
from __future__ import annotations

from decimal import Decimal

from kainext_binance_mcp.models import (
    BacktestResult,
    IndicatorResult,
    Kline,
    Ticker24h,
)


def test_kline_construct_decimal_ohlcv() -> None:
    k = Kline(
        open_time=1717000000000,
        open=Decimal("100.5"),
        high=Decimal("101.0"),
        low=Decimal("99.0"),
        close=Decimal("100.0"),
        volume=Decimal("1234.5"),
        close_time=1717003599999,
    )
    assert k.open_time == 1717000000000
    assert k.open == Decimal("100.5")
    assert isinstance(k.high, Decimal)
    assert k.close_time == 1717003599999


def test_ticker24h_construct() -> None:
    t = Ticker24h(
        symbol="BTCUSDT",
        price_change_pct=Decimal("2.5"),
        high=Decimal("70000"),
        low=Decimal("68000"),
        volume=Decimal("1000.0"),
        last=Decimal("69500"),
    )
    assert t.symbol == "BTCUSDT"
    assert isinstance(t.price_change_pct, Decimal)
    assert t.last == Decimal("69500")


def test_indicator_result_construct_float_series() -> None:
    r = IndicatorResult(
        symbol="ETHUSDT",
        interval="1h",
        indicators={"rsi": [None, None, 55.3, 60.1], "ema": [10.0, 10.5, 11.0, 11.2]},
        as_of=1717003599999,
    )
    assert r.indicators["rsi"][2] == 55.3
    assert r.indicators["rsi"][0] is None
    assert r.interval == "1h"


def test_backtest_result_construct_float_metrics() -> None:
    b = BacktestResult(
        symbol="BTCUSDT",
        interval="1d",
        strategy="ema_cross",
        total_return_pct=12.5,
        buy_hold_return_pct=8.0,
        n_trades=4,
        win_rate=0.75,
        max_drawdown_pct=-5.2,
        disclaimer="backtest != resultado futuro; sin slippage; muestra limitada",
    )
    assert b.strategy == "ema_cross"
    assert isinstance(b.total_return_pct, float)
    assert b.n_trades == 4
    assert "slippage" in b.disclaimer
