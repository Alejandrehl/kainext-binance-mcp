"""Knobs y helpers compartidos de capa 4 (señal en vivo y su backtest).

Antes duplicados entre tools/signals.py y signals/backtest_signal.py — divergían en
silencio. Los knobs están alineados con capa 2 (spec §4)."""
from __future__ import annotations

import pandas as pd

# Knobs por defecto de los indicadores de la señal compuesta.
EMA_FAST = 12
EMA_SLOW = 26
RSI_PERIOD = 14
BOLL_PERIOD = 20
BOLL_K = 2.0
ATR_PERIOD = 14


def bb_position(price: float, lower: float, upper: float) -> float:
    """Posición %B del precio dentro de las bandas de Bollinger: 0 = inferior, 1 = superior.

    Si las bandas colapsan (upper == lower, serie plana) devuelve 0.5 (neutro: sin señal).
    """
    width = upper - lower
    if width <= 0.0:
        return 0.5
    return (price - lower) / width


def last_valid(series: pd.Series, default: float = 0.0) -> float:
    """Último valor no-NaN de una serie de indicador (el del cierre más reciente utilizable).

    Devuelve ``default`` si toda la serie es NaN — un factor sin dato calculable queda en su
    neutro (0.0 para EMA/MACD/ATR, 50.0 para RSI; por eso es parametrizable).
    """
    s = series.dropna()
    if s.empty:
        return default
    return float(s.iloc[-1])


def value_at(series: pd.Series, i: int, default: float) -> float:
    """Valor del indicador en la vela ``i``; ``default`` si es NaN (calentamiento).

    Mismo criterio de neutro que ``last_valid``.
    """
    v = series.iloc[i]
    if pd.isna(v):
        return default
    return float(v)
