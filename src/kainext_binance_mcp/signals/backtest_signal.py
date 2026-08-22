"""Backtest de la señal compuesta de capa 4 — 100% read-only (spec capa-4-backtest).

Mide si la señal TÉCNICA del engine de capa 4 tiene *edge* real sobre históricos, **sin
lookahead**, antes de confiarle plata. Reúsa, sin reescribir:

- el engine PURO de capa 4 (``signals.engine.generate_signal``) por vela, y
- el harness anti-lookahead de capa 2 (``backtest.backtest_df`` + su param
  ``_signal_override``: posiciones decididas al ``close`` de la vela, fill en ``open[i]``).

**Limitación dura y documentada (la honestidad importa):** NO hay sentiment histórico por
vela (no tenemos archivo de noticias minuto a minuto), así que el backtest corre con
``sentiment=0`` — mide SÓLO la parte técnica (tendencia, momentum, MACD, Bollinger). El
``disclaimer`` lo deja explícito.

**Anti-lookahead:** los indicadores son causales (EMA/RSI/MACD/Bollinger/ATR en la vela
``i`` dependen sólo de datos ≤ ``i``), así que ``positions[i]`` se decide con indicadores
``≤ i``; el fill simulado usa ``open[i+1]`` (lo aporta el harness de capa 2). Cambiar el
``close`` de la última vela no puede alterar posiciones ni trades previos.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pandas as pd

from kainext_binance_mcp import indicators as ind
from kainext_binance_mcp.backtest import COMMISSION_TAKER, DISCLAIMER, backtest_df
from kainext_binance_mcp.models import BacktestResult
from kainext_binance_mcp.signals import common, engine

# Knobs de indicadores: en signals/common.py (compartidos con la tool generate_signal).

# Etiqueta honesta de la "estrategia" en el BacktestResult (no es una de capa 2).
_STRATEGY_LABEL = "composite_technical_signal"

# Disclaimer ampliado: el de capa 2 + la exclusión EXPLÍCITA del sentiment (spec §0).
SIGNAL_DISCLAIMER: str = (
    DISCLAIMER
    + " IMPORTANTE: este backtest mide SÓLO la parte TÉCNICA de la señal compuesta de "
    "capa 4 (tendencia, momentum, MACD, Bollinger). El factor de SENTIMENT se EXCLUYE "
    "(sentiment=0 en cada vela) porque no existe sentiment histórico por vela; el "
    "sentiment es un ajuste en vivo, no backtesteable acá. Por lo tanto no representa la "
    "señal completa, sólo su componente técnico."
)


def signal_positions(
    df: pd.DataFrame,
    weights: Mapping[str, float] | None = None,
    threshold: float | None = None,
) -> list[int]:
    """Serie de posiciones {0, 1} por vela según el engine de capa 4 (sentiment=0).

    Calcula los indicadores sobre TODA la serie (son causales → ``indicadores[i]`` usa sólo
    datos ≤ ``i``) y, para cada vela ``i``, arma los inputs del engine (EMA fast/slow, RSI,
    histograma MACD, posición Bollinger, ATR) con ``sentiment=0.0``, llama
    ``engine.generate_signal`` y mapea la dirección: ``long`` → 1, ``hold``/``avoid`` → 0.

    Anti-lookahead: como los indicadores en ``i`` no miran velas > ``i``, ``positions[i]`` no
    depende del futuro. El fill (vela siguiente) lo aporta el harness de capa 2.
    """
    thr = engine.DEFAULT_THRESHOLD if threshold is None else threshold
    n = len(df)
    if n == 0:
        return []

    close = df["close"]
    ema_fast = ind.ema(close, common.EMA_FAST)
    ema_slow = ind.ema(close, common.EMA_SLOW)
    rsi = ind.rsi(close, common.RSI_PERIOD)
    _macd_line, _signal_line, hist = ind.macd(close)
    upper, _mid, lower = ind.bollinger(close, common.BOLL_PERIOD, common.BOLL_K)
    atr = ind.atr(df["high"], df["low"], close, common.ATR_PERIOD)

    positions: list[int] = []
    for i in range(n):
        price_f = float(close.iloc[i])
        bb_pos = common.bb_position(price_f, common.value_at(lower, i, price_f),
                                    common.value_at(upper, i, price_f))
        signal = engine.generate_signal(
            symbol="",
            interval="",
            price=Decimal(str(price_f)),
            ema_fast=common.value_at(ema_fast, i, 0.0),
            ema_slow=common.value_at(ema_slow, i, 0.0),
            rsi=common.value_at(rsi, i, 50.0),  # sin RSI → momentum neutro
            macd_hist=common.value_at(hist, i, 0.0),
            bb_pos=bb_pos,
            sentiment=0.0,  # EXCLUIDO: no hay sentiment histórico por vela (spec §0).
            atr=common.value_at(atr, i, 0.0),
            weights=weights,
            threshold=thr,
            as_of=0,
        )
        positions.append(1 if signal.direction == "long" else 0)
    return positions


def backtest_signal(
    df: pd.DataFrame,
    weights: Mapping[str, float] | None = None,
    threshold: float | None = None,
    commission: float = COMMISSION_TAKER,
    *,
    symbol: str = "",
    interval: str = "",
) -> BacktestResult:
    """Backtestea la señal técnica compuesta sobre un DataFrame de klines (read-only).

    Construye las posiciones con :func:`signal_positions` (sin lookahead, sentiment=0) y las
    inyecta al harness de capa 2 vía ``_signal_override``; devuelve el ``BacktestResult`` de
    capa 2 con la etiqueta y el ``disclaimer`` ampliados (exclusión EXPLÍCITA del sentiment).
    """
    positions = signal_positions(df, weights=weights, threshold=threshold)
    override = pd.Series(positions, index=df.index, dtype="int64")

    # backtest_df valida ``strategy`` contra el enum de capa 2 ANTES de usar el override;
    # pasamos un nombre válido (nunca se ejecuta, el override manda) y reetiquetamos abajo.
    base = backtest_df(
        df,
        symbol=symbol,
        interval=interval,
        strategy="ema_cross",
        commission=commission,
        _signal_override=override,
    )
    return base.model_copy(
        update={"strategy": _STRATEGY_LABEL, "disclaimer": SIGNAL_DISCLAIMER}
    )
