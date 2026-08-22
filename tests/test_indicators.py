"""Tests de indicadores con GOLDEN VALUES calculados a mano (spec §4).

Cada golden está derivado a mano en los comentarios para poder auditarlo:
- EMA([1,2,3,4,5], n=3): alpha=2/(3+1)=0.5, recursión sembrada en el primer valor:
    e0=1; e1=.5*2+.5*1=1.5; e2=.5*3+.5*1.5=2.25; e3=.5*4+.5*2.25=3.125;
    e4=.5*5+.5*3.125=4.0625  -> último = 4.0625
- RSI Wilder: serie creciente monótona => sólo ganancias, avgLoss=0 => RS=inf => RSI=100 (>70).
    Serie decreciente monótona => sólo pérdidas, avgGain=0 => RS=0 => RSI=0 (<30).
- MACD de serie constante: EMA de constante = constante => EMA12=EMA26=c => macd=0;
    signal=EMA9(0)=0; hist=0.
- Bollinger(constante c, n=20): SMA=c, std=0 => upper=mid=lower=c.
- ATR(14) con high=11, low=9, close=10 constantes => TR=max(11-9, |11-10|, |9-10|)=max(2,1,1)=2=H;
    suavizado Wilder de TR constante = 2 = H.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from kainext_binance_mcp.indicators import atr, bollinger, ema, macd, rsi


def test_ema_golden_alpha_half() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ema(s, 3)
    assert math.isclose(float(out.iloc[-1]), 4.0625, rel_tol=1e-12)
    # serie completa esperada
    expected = [1.0, 1.5, 2.25, 3.125, 4.0625]
    for got, exp in zip(out.tolist(), expected, strict=True):
        assert math.isclose(float(got), exp, rel_tol=1e-12)


def test_rsi_increasing_above_70() -> None:
    s = pd.Series([float(i) for i in range(1, 31)])  # estrictamente creciente
    out = rsi(s, 14)
    last = float(out.iloc[-1])
    assert last > 70.0
    assert math.isclose(last, 100.0, rel_tol=1e-9)  # sin pérdidas => 100


def test_rsi_decreasing_below_30() -> None:
    s = pd.Series([float(i) for i in range(30, 0, -1)])  # estrictamente decreciente
    out = rsi(s, 14)
    last = float(out.iloc[-1])
    assert last < 30.0
    assert math.isclose(last, 0.0, abs_tol=1e-9)  # sin ganancias => 0


def test_rsi_bounded_0_100() -> None:
    s = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 5.0, 7.0, 6.0, 8.0,
                   7.0, 9.0, 8.0, 10.0, 9.0, 11.0, 10.0, 12.0])
    out = rsi(s, 14).dropna()
    assert (out >= 0.0).all()
    assert (out <= 100.0).all()


def test_macd_constant_series_zero() -> None:
    s = pd.Series([100.0] * 60)
    line, signal, hist = macd(s)
    assert math.isclose(float(line.iloc[-1]), 0.0, abs_tol=1e-12)
    assert math.isclose(float(signal.iloc[-1]), 0.0, abs_tol=1e-12)
    assert math.isclose(float(hist.iloc[-1]), 0.0, abs_tol=1e-12)


def test_macd_relation_hist_equals_line_minus_signal() -> None:
    s = pd.Series([float(i % 7) + 100.0 for i in range(80)])
    line, signal, hist = macd(s)
    diff = (line - signal - hist).dropna()
    assert (diff.abs() < 1e-9).all()


def test_bollinger_constant_collapses() -> None:
    c = 42.0
    s = pd.Series([c] * 30)
    upper, mid, lower = bollinger(s, 20, 2)
    assert math.isclose(float(upper.iloc[-1]), c, abs_tol=1e-12)
    assert math.isclose(float(mid.iloc[-1]), c, abs_tol=1e-12)
    assert math.isclose(float(lower.iloc[-1]), c, abs_tol=1e-12)


def test_bollinger_ordering() -> None:
    s = pd.Series([float(i % 5) + 10.0 for i in range(40)])
    upper, mid, lower = bollinger(s, 20, 2)
    u, m, low = upper.dropna(), mid.dropna(), lower.dropna()
    assert (u >= m).all()
    assert (m >= low).all()


def test_atr_constant_range_equals_h() -> None:
    n = 40
    high = pd.Series([11.0] * n)
    low = pd.Series([9.0] * n)
    close = pd.Series([10.0] * n)
    out = atr(high, low, close, 14)
    assert math.isclose(float(out.iloc[-1]), 2.0, rel_tol=1e-12)  # H = 2


def test_invalid_n_raises() -> None:
    s = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="n must be > 0"):
        ema(s, 0)
    with pytest.raises(ValueError, match="n must be > 0"):
        rsi(s, 0)
    with pytest.raises(ValueError, match="n must be > 0"):
        bollinger(s, 0)
    with pytest.raises(ValueError, match="n must be > 0"):
        atr(s, s, s, 0)
