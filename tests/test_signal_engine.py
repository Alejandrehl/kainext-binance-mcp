"""Tests del motor de señales (plan Task 2, spec §5/§6). Inputs sintéticos verificables a mano.

El engine es PURO: recibe indicadores ya calculados + sentiment y devuelve un ``Signal``.
Acá fijamos cada factor por separado (con el resto neutro) para auditar su contribución
exacta, luego combinaciones, niveles ATR y la dirección por umbral. Cobertura ≥95.

Convenciones de neutralidad (contribución 0 de un factor):
- trend: ema_fast == ema_slow → 0.
- momentum: rsi == 50 → 0.
- macd: macd_hist == 0 → 0.
- bollinger: bb_pos == 0.5 (en la media) → 0.
- sentiment: sentiment == 0.0 → 0.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from kainext_binance_mcp.models import Signal
from kainext_binance_mcp.signals.engine import (
    DEFAULT_ATR_MULT,
    DEFAULT_RR,
    DEFAULT_THRESHOLD,
    DEFAULT_WEIGHTS,
    generate_signal,
)

# Entradas neutras base: cada test sobreescribe sólo el factor que quiere medir.
_NEUTRAL = dict(
    symbol="BTCUSDT",
    interval="1h",
    price=Decimal("100"),
    ema_fast=10.0,
    ema_slow=10.0,
    rsi=50.0,
    macd_hist=0.0,
    bb_pos=0.5,
    sentiment=0.0,
    atr=2.0,
    as_of=1717003599999,
)


def _gen(**overrides: object) -> Signal:
    kwargs = {**_NEUTRAL, **overrides}
    return generate_signal(**kwargs)  # type: ignore[arg-type]


def _factor(sig: Signal, name: str) -> object:
    return next(f for f in sig.factors if f.name == name)


# --------------------------------------------------------------------------- #
# Defaults documentados
# --------------------------------------------------------------------------- #

def test_default_weights_documented() -> None:
    assert DEFAULT_WEIGHTS == {
        "trend": 0.30,
        "momentum": 0.20,
        "macd": 0.20,
        "bollinger": 0.15,
        "sentiment": 0.15,
    }
    # Suma 1.0: un score "saturado" en todos los factores llega a ±1.
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
    assert DEFAULT_THRESHOLD == 0.15
    assert DEFAULT_ATR_MULT == 1.5
    assert DEFAULT_RR == 2.0


# --------------------------------------------------------------------------- #
# Factores aislados
# --------------------------------------------------------------------------- #

def test_trend_bullish_only() -> None:
    s = _gen(ema_fast=11.0, ema_slow=10.0)
    f = _factor(s, "trend")
    assert f.value == 1.0
    assert f.contribution == pytest.approx(0.30)
    # Resto neutro → score == contribución de tendencia.
    assert s.score == pytest.approx(0.30)
    assert s.direction == "long"  # 0.30 ≥ umbral 0.15


def test_trend_bearish_only() -> None:
    s = _gen(ema_fast=9.0, ema_slow=10.0)
    f = _factor(s, "trend")
    assert f.value == -1.0
    assert f.contribution == pytest.approx(-0.30)
    assert s.score == pytest.approx(-0.30)
    assert s.direction == "avoid"


def test_trend_flat_is_zero() -> None:
    s = _gen(ema_fast=10.0, ema_slow=10.0)
    assert _factor(s, "trend").value == 0.0
    assert _factor(s, "trend").contribution == 0.0


def test_momentum_oversold_positive() -> None:
    # rsi=30 → value = (50-30)/20 = +1.0 → contribución +0.20.
    s = _gen(rsi=30.0)
    f = _factor(s, "momentum")
    assert f.value == pytest.approx(1.0)
    assert f.contribution == pytest.approx(0.20)
    assert s.score == pytest.approx(0.20)


def test_momentum_overbought_negative() -> None:
    # rsi=70 → value = (50-70)/20 = -1.0 → contribución -0.20.
    s = _gen(rsi=70.0)
    assert _factor(s, "momentum").value == pytest.approx(-1.0)
    assert _factor(s, "momentum").contribution == pytest.approx(-0.20)


def test_momentum_linear_midrange() -> None:
    # rsi=40 → value = (50-40)/20 = +0.5 → contribución +0.10.
    s = _gen(rsi=40.0)
    assert _factor(s, "momentum").value == pytest.approx(0.5)
    assert _factor(s, "momentum").contribution == pytest.approx(0.10)


def test_momentum_clamped_extremes() -> None:
    # rsi=10 → (50-10)/20 = +2.0 → recortado a +1.0.
    s_low = _gen(rsi=10.0)
    assert _factor(s_low, "momentum").value == pytest.approx(1.0)
    # rsi=90 → (50-90)/20 = -2.0 → recortado a -1.0.
    s_high = _gen(rsi=90.0)
    assert _factor(s_high, "momentum").value == pytest.approx(-1.0)


def test_macd_positive() -> None:
    s = _gen(macd_hist=0.5)
    assert _factor(s, "macd").value == 1.0
    assert _factor(s, "macd").contribution == pytest.approx(0.20)


def test_macd_negative() -> None:
    s = _gen(macd_hist=-0.5)
    assert _factor(s, "macd").value == -1.0
    assert _factor(s, "macd").contribution == pytest.approx(-0.20)


def test_macd_zero() -> None:
    s = _gen(macd_hist=0.0)
    assert _factor(s, "macd").value == 0.0
    assert _factor(s, "macd").contribution == 0.0


def test_bollinger_near_lower_positive() -> None:
    # bb_pos=0 (banda inferior) → value = 1-2*0 = +1 → +0.15 (posible rebote).
    s = _gen(bb_pos=0.0)
    assert _factor(s, "bollinger").value == pytest.approx(1.0)
    assert _factor(s, "bollinger").contribution == pytest.approx(0.15)


def test_bollinger_near_upper_negative() -> None:
    # bb_pos=1 (banda superior) → value = 1-2*1 = -1 → -0.15.
    s = _gen(bb_pos=1.0)
    assert _factor(s, "bollinger").value == pytest.approx(-1.0)
    assert _factor(s, "bollinger").contribution == pytest.approx(-0.15)


def test_bollinger_mid_zero() -> None:
    s = _gen(bb_pos=0.5)
    assert _factor(s, "bollinger").value == pytest.approx(0.0)
    assert _factor(s, "bollinger").contribution == pytest.approx(0.0)


def test_bollinger_clamped_outside_bands() -> None:
    # bb_pos=1.5 (sobre la banda superior) → 1-2*1.5 = -2 → recortado a -1.
    s = _gen(bb_pos=1.5)
    assert _factor(s, "bollinger").value == pytest.approx(-1.0)


def test_sentiment_passthrough() -> None:
    # sentiment +0.8 → contribución +0.8*0.15 = +0.12.
    s = _gen(sentiment=0.8)
    assert _factor(s, "sentiment").value == pytest.approx(0.8)
    assert _factor(s, "sentiment").contribution == pytest.approx(0.12)


def test_sentiment_clamped() -> None:
    # un sentiment fuera de rango se recorta a [-1, 1] antes de ponderar.
    s = _gen(sentiment=-3.0)
    assert _factor(s, "sentiment").value == pytest.approx(-1.0)
    assert _factor(s, "sentiment").contribution == pytest.approx(-0.15)


# --------------------------------------------------------------------------- #
# Combinaciones, clip y dirección
# --------------------------------------------------------------------------- #

def test_all_factors_present() -> None:
    s = _gen()
    names = {f.name for f in s.factors}
    assert names == {"trend", "momentum", "macd", "bollinger", "sentiment"}
    assert len(s.factors) == 5


def test_combined_sum_of_contributions() -> None:
    # trend bull (+0.30) + macd bull (+0.20) + sentiment +0.5 (+0.075) = +0.575.
    s = _gen(ema_fast=11.0, ema_slow=10.0, macd_hist=1.0, sentiment=0.5)
    assert s.score == pytest.approx(0.30 + 0.20 + 0.075)
    assert s.direction == "long"


def test_score_clipped_to_one() -> None:
    # Todo máximo alcista: 0.30+0.20+0.20+0.15+0.15 = 1.0 (sin clip aún) → con sentiment>1
    # forzamos la saturación; el clip mantiene score ≤ 1.
    s = _gen(ema_fast=11.0, ema_slow=10.0, rsi=10.0, macd_hist=1.0, bb_pos=0.0, sentiment=1.0)
    assert s.score == pytest.approx(1.0)


def test_score_clipped_to_minus_one() -> None:
    s = _gen(ema_fast=9.0, ema_slow=10.0, rsi=90.0, macd_hist=-1.0, bb_pos=1.0, sentiment=-1.0)
    assert s.score == pytest.approx(-1.0)


def test_direction_hold_in_neutral_zone() -> None:
    # sólo sentiment +0.5 → 0.075 < umbral 0.15 → hold.
    s = _gen(sentiment=0.5)
    assert s.score == pytest.approx(0.075)
    assert s.direction == "hold"
    assert s.suggested_stop is None
    assert s.suggested_target is None


def test_direction_long_at_exact_threshold() -> None:
    # Forzamos score == umbral exacto con un threshold custom: sentiment 1.0*0.15 = 0.15.
    s = _gen(sentiment=1.0, threshold=0.15)
    assert s.score == pytest.approx(0.15)
    assert s.direction == "long"  # ≥ umbral


def test_direction_avoid_at_exact_negative_threshold() -> None:
    s = _gen(sentiment=-1.0, threshold=0.15)
    assert s.score == pytest.approx(-0.15)
    assert s.direction == "avoid"


# --------------------------------------------------------------------------- #
# Niveles ATR
# --------------------------------------------------------------------------- #

def test_atr_levels_long() -> None:
    # price=100, atr=2, atr_mult=1.5, rr=2 →
    # stop = 100 - 1.5*2 = 97 ; target = 100 + 2*1.5*2 = 106.
    s = _gen(ema_fast=11.0, ema_slow=10.0, price=Decimal("100"), atr=2.0)
    assert s.direction == "long"
    assert s.suggested_stop == Decimal("97.0")
    assert s.suggested_target == Decimal("106.0")
    assert s.suggested_stop < s.price < s.suggested_target


def test_atr_levels_avoid_inverted() -> None:
    # Para "avoid" los niveles se invierten (protección al alza si tenés/quieres salir):
    # stop = price + atr_mult*atr = 103 ; target = price - rr*atr_mult*atr = 94.
    s = _gen(ema_fast=9.0, ema_slow=10.0, price=Decimal("100"), atr=2.0)
    assert s.direction == "avoid"
    assert s.suggested_stop == Decimal("103.0")
    assert s.suggested_target == Decimal("94.0")
    assert s.suggested_target < s.price < s.suggested_stop


def test_atr_levels_hold_none() -> None:
    s = _gen()  # todo neutro → hold
    assert s.direction == "hold"
    assert s.suggested_stop is None
    assert s.suggested_target is None


def test_atr_levels_custom_mult_and_rr() -> None:
    # atr_mult=2, rr=3, price=200, atr=5 →
    # stop = 200 - 2*5 = 190 ; target = 200 + 3*2*5 = 230.
    s = _gen(ema_fast=11.0, ema_slow=10.0, price=Decimal("200"), atr=5.0, atr_mult=2.0, rr=3.0)
    assert s.suggested_stop == Decimal("190.0")
    assert s.suggested_target == Decimal("230.0")


# --------------------------------------------------------------------------- #
# Pesos custom + metadatos
# --------------------------------------------------------------------------- #

def test_custom_weights() -> None:
    weights = {"trend": 0.5, "momentum": 0.0, "macd": 0.0, "bollinger": 0.0, "sentiment": 0.5}
    s = _gen(ema_fast=11.0, ema_slow=10.0, sentiment=1.0, weights=weights)
    # trend 1*0.5 + sentiment 1*0.5 = 1.0.
    assert s.score == pytest.approx(1.0)
    assert _factor(s, "momentum").contribution == 0.0


def test_metadata_populated() -> None:
    s = _gen(ema_fast=11.0, ema_slow=10.0)
    assert s.symbol == "BTCUSDT"
    assert s.interval == "1h"
    assert s.price == Decimal("100")
    assert s.atr == 2.0
    assert s.as_of == 1717003599999
    assert s.disclaimer
    assert "predicc" in s.disclaimer.lower() or "no es" in s.disclaimer.lower()


def test_factor_notes_are_human_readable() -> None:
    s = _gen(ema_fast=11.0, ema_slow=10.0, rsi=25.0, macd_hist=0.3, bb_pos=0.1, sentiment=0.6)
    for f in s.factors:
        assert isinstance(f.note, str) and f.note  # no vacío
