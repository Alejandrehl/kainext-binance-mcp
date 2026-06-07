"""Tests de construcción de los modelos de capa 4 (plan Task 1, spec §4).

``SignalFactor`` lleva valores analíticos en float; ``Signal`` lleva precio y niveles de
riesgo en Decimal (E3, consistencia con capa 1) y la dirección como Literal cerrado.
"""
from __future__ import annotations

from decimal import Decimal

from kainext_binance_mcp.models import Signal, SignalFactor


def test_signal_factor_construct() -> None:
    f = SignalFactor(
        name="trend",
        value=1.0,
        weight=0.30,
        contribution=0.30,
        note="EMA fast > EMA slow (tendencia alcista)",
    )
    assert f.name == "trend"
    assert f.value == 1.0
    assert isinstance(f.value, float)
    assert f.weight == 0.30
    assert f.contribution == 0.30
    assert "EMA" in f.note


def test_signal_construct_long_with_levels() -> None:
    factors = [
        SignalFactor(name="trend", value=1.0, weight=0.30, contribution=0.30, note="up"),
        SignalFactor(name="momentum", value=0.5, weight=0.20, contribution=0.10, note="oversold-ish"),
    ]
    s = Signal(
        symbol="BTCUSDT",
        interval="1h",
        direction="long",
        score=0.40,
        factors=factors,
        price=Decimal("69500.00"),
        suggested_stop=Decimal("68000.00"),
        suggested_target=Decimal("72500.00"),
        atr=750.0,
        disclaimer="no es predicción; heurística compuesta; validar con backtest",
        as_of=1717003599999,
    )
    assert s.symbol == "BTCUSDT"
    assert s.direction == "long"
    assert s.score == 0.40
    assert len(s.factors) == 2
    assert isinstance(s.price, Decimal)
    assert isinstance(s.suggested_stop, Decimal)
    assert s.suggested_stop < s.price < s.suggested_target
    assert s.atr == 750.0
    assert "predicción" in s.disclaimer
    assert s.as_of == 1717003599999


def test_signal_construct_hold_without_levels() -> None:
    s = Signal(
        symbol="ETHUSDT",
        interval="4h",
        direction="hold",
        score=0.05,
        factors=[],
        price=Decimal("3500.00"),
        suggested_stop=None,
        suggested_target=None,
        atr=42.0,
        disclaimer="zona neutra",
        as_of=1717003599999,
    )
    assert s.direction == "hold"
    assert s.suggested_stop is None
    assert s.suggested_target is None
    assert s.factors == []
