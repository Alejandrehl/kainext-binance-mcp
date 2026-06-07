"""Tests del backtest de la señal compuesta de capa 4 (spec capa-4-backtest §2).

El backtest mide si la señal TÉCNICA (engine de capa 4 con ``sentiment=0``) tiene edge,
SIN LOOKAHEAD, reusando el harness anti-lookahead de capa 2 (``backtest_df`` + el param
``_signal_override``). Tres ejes verificados:

1. **Anti-lookahead (crítico):** los indicadores son causales → ``positions[i]`` se decide
   con datos ≤ ``i``. Cambiar el ``close`` de la última vela NO altera ni las posiciones ni
   los trades previos.
2. **Comportamiento:** sobre una serie tendencial sintética, la señal entra (long) en la
   subida y sale (flat) en la bajada, como se espera del engine.
3. **Métricas coherentes** y disclaimer que deja EXPLÍCITA la exclusión del sentiment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from kainext_binance_mcp.models import BacktestResult
from kainext_binance_mcp.signals.backtest_signal import (
    backtest_signal,
    signal_positions,
)


def _df_from_closes(closes: list[float]) -> pd.DataFrame:
    """DataFrame de klines sintético: OHLC derivado del close, volumen constante.

    open[i] = close[i-1] (continuidad), high/low con un colchón fijo. Suficiente para
    alimentar EMA/RSI/MACD/Bollinger/ATR de forma determinista.
    """
    n = len(closes)
    base = 1_717_000_000_000
    opens = [closes[0]] + closes[:-1]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    return pd.DataFrame(
        {
            "open_time": pd.Series([base + i * 3_600_000 for i in range(n)], dtype="int64"),
            "open": pd.Series(opens, dtype="float64"),
            "high": pd.Series(highs, dtype="float64"),
            "low": pd.Series(lows, dtype="float64"),
            "close": pd.Series(closes, dtype="float64"),
            "volume": pd.Series([10.0] * n, dtype="float64"),
            "close_time": pd.Series(
                [base + i * 3_600_000 + 3_599_999 for i in range(n)], dtype="int64"
            ),
        }
    )


def _trend_then_reversal(up: int = 60, down: int = 60, start: float = 100.0) -> pd.DataFrame:
    """Sube de forma sostenida y luego cae: la señal técnica debería entrar y luego salir."""
    closes = [start + i for i in range(up)]
    top = closes[-1]
    closes += [top - (j + 1) for j in range(down)]
    return _df_from_closes(closes)


# --------------------------------------------------------------------------- #
# signal_positions: forma y dominio
# --------------------------------------------------------------------------- #

def test_signal_positions_returns_binary_list_aligned_to_df() -> None:
    df = _trend_then_reversal()
    pos = signal_positions(df)
    assert isinstance(pos, list)
    assert len(pos) == len(df)
    assert all(p in (0, 1) for p in pos)


# --------------------------------------------------------------------------- #
# Anti-lookahead (el invariante que importa)
# --------------------------------------------------------------------------- #

def test_signal_positions_no_lookahead_last_candle_does_not_change_past() -> None:
    """Cambiar el close de la ÚLTIMA vela no altera ninguna posición previa."""
    df = _trend_then_reversal()
    base_pos = signal_positions(df)

    mutated = df.copy()
    # Shock brutal en la última vela (×3): si hubiera lookahead, contaminaría el pasado.
    mutated.loc[mutated.index[-1], "close"] = df["close"].iloc[-1] * 3.0
    mutated.loc[mutated.index[-1], "high"] = df["close"].iloc[-1] * 3.0 + 1.0
    mut_pos = signal_positions(mutated)

    # Todas las posiciones menos la última deben ser idénticas.
    assert mut_pos[:-1] == base_pos[:-1]


def test_position_at_i_depends_only_on_candles_up_to_i() -> None:
    """positions[i] no depende de velas > i: truncar la serie en i da el mismo valor."""
    df = _trend_then_reversal()
    full = signal_positions(df)
    # Cortamos en un punto arbitrario (después del calentamiento) y comparamos.
    cut = 80
    truncated = signal_positions(df.iloc[: cut + 1].reset_index(drop=True))
    assert truncated[cut] == full[cut]
    assert truncated == full[: cut + 1]


def test_backtest_signal_trades_unchanged_by_last_close() -> None:
    """A nivel de trades cerrados: mutar el último close no cambia n_trades ni win_rate."""
    df = _trend_then_reversal()
    res = backtest_signal(df, symbol="SYN", interval="1h")

    mutated = df.copy()
    mutated.loc[mutated.index[-1], "close"] = df["close"].iloc[-1] * 0.2  # crash en la última
    mutated.loc[mutated.index[-1], "low"] = df["close"].iloc[-1] * 0.2 - 1.0
    res_mut = backtest_signal(mutated, symbol="SYN", interval="1h")

    assert res_mut.n_trades == res.n_trades
    assert res_mut.win_rate == res.win_rate


# --------------------------------------------------------------------------- #
# Comportamiento sobre serie tendencial
# --------------------------------------------------------------------------- #

def test_signal_enters_long_during_uptrend() -> None:
    """En una subida sostenida y larga, la señal técnica termina en long (posición 1)."""
    closes = [100.0 + i for i in range(120)]  # monótona creciente
    df = _df_from_closes(closes)
    pos = signal_positions(df)
    # Tras el calentamiento, en plena tendencia alcista la posición es long.
    assert pos[-1] == 1
    assert sum(pos) > 0  # entró al menos una vez


def test_signal_exits_on_reversal() -> None:
    """Subida y luego caída pronunciada: la señal sale (flat) hacia el final."""
    df = _trend_then_reversal(up=60, down=70)
    pos = signal_positions(df)
    assert pos[-1] == 0  # en plena bajada, fuera del mercado
    # Hubo al menos un round-trip (entró en la subida, salió en la bajada).
    res = backtest_signal(df, symbol="SYN", interval="1h")
    assert res.n_trades >= 1


# --------------------------------------------------------------------------- #
# Métricas + disclaimer
# --------------------------------------------------------------------------- #

def test_backtest_signal_returns_coherent_metrics() -> None:
    df = _trend_then_reversal()
    res = backtest_signal(df, symbol="BTCUSDT", interval="4h")
    assert isinstance(res, BacktestResult)
    assert res.symbol == "BTCUSDT"
    assert res.interval == "4h"
    assert res.n_trades >= 0
    assert 0.0 <= res.win_rate <= 1.0
    assert res.max_drawdown_pct >= 0.0
    assert np.isfinite(res.total_return_pct)
    assert np.isfinite(res.buy_hold_return_pct)


def test_disclaimer_makes_sentiment_exclusion_explicit() -> None:
    """El disclaimer debe dejar EXPLÍCITO que el sentiment se excluye (sólo parte técnica)."""
    df = _trend_then_reversal()
    res = backtest_signal(df, symbol="SYN", interval="1h")
    low = res.disclaimer.lower()
    assert "sentiment" in low
    assert "técnic" in low  # "técnica"/"técnico"
    assert res.strategy != "ema_cross"  # etiqueta honesta, no la de capa 2


def test_threshold_changes_positions() -> None:
    """Un umbral muy alto vuelve a la señal más conservadora (≤ posiciones long)."""
    df = _trend_then_reversal()
    low_thr = sum(signal_positions(df, threshold=0.05))
    high_thr = sum(signal_positions(df, threshold=0.95))
    assert high_thr <= low_thr


def test_signal_positions_empty_df_returns_empty() -> None:
    """DataFrame vacío → lista vacía (no rompe; camino degenerado honesto)."""
    empty = _df_from_closes([100.0]).iloc[0:0]
    assert signal_positions(empty) == []


def test_backtest_signal_short_series_is_safe() -> None:
    """Muestra insuficiente (<2 velas): no rompe, métricas en cero (honesto)."""
    df = _df_from_closes([100.0])
    res = backtest_signal(df, symbol="SYN", interval="1h")
    assert res.n_trades == 0
    assert res.total_return_pct == 0.0
    # Disclaimer ampliado sigue presente aun en el camino degenerado.
    assert "sentiment" in res.disclaimer.lower()
