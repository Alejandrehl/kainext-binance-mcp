"""Harness de backtest liviano en pandas, SIN LOOKAHEAD (spec §5, E5).

Honesto por diseño:
- **Anti-lookahead (crítico):** la señal de la vela ``t`` se calcula con datos hasta el
  cierre de ``t``; la ejecución simulada usa el ``open`` de ``t+1``. Nunca se ejecuta al
  ``close`` de la propia vela que generó la señal. Concretamente, la posición que se
  mantiene *durante* la vela ``i`` la decide ``signal[i-1]`` y el fill ocurre en
  ``open[i]``. Como la última vela sólo podría generar un fill en ``open[last+1]`` (que
  no existe), cambiar su ``close`` no puede alterar trades ya cerrados.
- **Comisión:** taker 0.1% por lado (``COMMISSION_TAKER``), aplicada sobre el notional de
  cada fill (entrada y salida).
- **Sin slippage:** los fills usan el ``open`` exacto de la vela siguiente. Es una
  limitación documentada del modelo (mercado real tiene slippage/profundidad).
- **Long-only:** spot, posiciones en {flat=0, long=1}. No hay cortos.

Estrategias (enum, spec §5):
- ``ema_cross(fast, slow)``: long mientras EMA rápida > EMA lenta.
- ``rsi_threshold(low, high)``: entra long cuando RSI < ``low`` (sobreventa), sale cuando
  RSI > ``high`` (sobrecompra); mantiene el estado en el medio.

Métricas (todas ``float``; los indicadores/retornos son analíticos, no montos — E3):
- ``total_return_pct``: retorno compuesto de la estrategia (marca a ``close`` la posición
  abierta al final, sin forzar un fill de salida).
- ``buy_hold_return_pct``: comprar al primer ``open`` ejecutable (``open[1]``) y marcar al
  último ``close``.
- ``n_trades``: round-trips cerrados (entrada + salida).
- ``win_rate``: fracción de trades cerrados con retorno neto > 0 (0.0 si no hay trades).
- ``max_drawdown_pct``: magnitud (>= 0) de la peor caída pico-a-valle de la curva de equity
  marcada por vela.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from kainext_binance_mcp import indicators
from kainext_binance_mcp.models import BacktestResult

# Comisión taker por lado (0.1%). Default de Binance spot sin descuentos.
COMMISSION_TAKER: float = 0.001

DISCLAIMER: str = (
    "Backtest informativo, NO predice resultados futuros. Modelo sin slippage "
    "(fills al open exacto de la vela siguiente) y sobre una muestra limitada de "
    "históricos. Comisión taker 0.1% por lado. Úsese sólo como evidencia de apoyo, "
    "nunca como promesa de rendimiento."
)


@dataclass(frozen=True)
class Trade:
    """Un round-trip cerrado: entrada (open[t+1]) y salida (open[t'+1])."""

    entry_index: int
    entry_price: float
    exit_index: int
    exit_price: float
    return_pct: float  # neto de comisión en ambos lados, en %


# --------------------------------------------------------------------------- #
# Estrategias → señal {0, 1} alineada a las velas (decidida al close de cada vela)
# --------------------------------------------------------------------------- #

def ema_cross(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    """Long (1) mientras EMA(fast) > EMA(slow), flat (0) en caso contrario.

    La señal en la vela ``t`` usa sólo closes hasta ``t`` (las EMA son causales).
    """
    if fast <= 0 or slow <= 0:
        raise ValueError("fast y slow deben ser > 0")
    if fast >= slow:
        raise ValueError("fast must be < slow")
    close = df["close"]
    ema_fast = indicators.ema(close, fast)
    ema_slow = indicators.ema(close, slow)
    sig = (ema_fast > ema_slow).astype("int64")
    return sig


def rsi_threshold(
    df: pd.DataFrame, low: float = 30.0, high: float = 70.0, n: int = 14
) -> pd.Series:
    """Entra long cuando RSI < ``low``, sale cuando RSI > ``high``; mantiene en el medio.

    La señal en la vela ``t`` usa el RSI hasta ``t`` (causal).
    """
    if not (0.0 <= low < high <= 100.0):
        raise ValueError("se requiere 0 <= low < high <= 100")
    rsi = indicators.rsi(df["close"], n=n)
    # Estado puntual: 1 si sobreventa, 0 si sobrecompra, NaN si neutral (se hereda).
    raw = pd.Series(float("nan"), index=df.index)
    raw = raw.mask(rsi < low, 1.0)
    raw = raw.mask(rsi > high, 0.0)
    return raw.ffill().fillna(0.0).astype("int64")


# Registro de estrategias (enum de capa 2, spec §5).
STRATEGIES: dict[str, Callable[..., pd.Series]] = {
    "ema_cross": ema_cross,
    "rsi_threshold": rsi_threshold,
}


# --------------------------------------------------------------------------- #
# Simulación sin lookahead
# --------------------------------------------------------------------------- #

def simulate(
    df: pd.DataFrame, signal: pd.Series, commission: float = COMMISSION_TAKER
) -> tuple[list[Trade], list[float]]:
    """Simula la estrategia long-only y devuelve (trades_cerrados, curva_de_equity).

    Regla anti-lookahead: la posición a mantener *entrando* en la vela ``i`` la decide
    ``signal[i-1]`` (cierre de la vela previa) y el fill ocurre en ``open[i]``. Por eso el
    bucle empieza en ``i = 1`` y nunca mira ``close[i]`` para decidir el fill de ``i``.

    La curva de equity marca a ``close[i]`` el valor del portafolio en cada vela (cash si
    está flat, ``units * close[i]`` si está long), partiendo de capital 1.0.
    """
    opens = df["open"].to_numpy(dtype="float64")
    closes = df["close"].to_numpy(dtype="float64")
    sig = signal.to_numpy()
    n = len(df)

    trades: list[Trade] = []
    equity_curve: list[float] = []

    cash = 1.0
    units = 0.0
    pos = 0  # posición actual: 0 flat, 1 long
    entry_index = -1
    entry_price = 0.0
    entry_cost = 0.0  # cash gastado al entrar (incluye comisión), para el retorno del trade

    # Vela 0: nunca hay fill (no existe signal[-1] ejecutable); marcamos equity inicial.
    equity_curve.append(cash)

    for i in range(1, n):
        target = int(sig[i - 1])  # decidido al close de i-1 => fill en open[i]
        fill_price = opens[i]

        if target == 1 and pos == 0:
            # Entrar long en open[i].
            entry_cost = cash
            units = (cash * (1.0 - commission)) / fill_price
            cash = 0.0
            pos = 1
            entry_index = i
            entry_price = fill_price
        elif target == 0 and pos == 1:
            # Salir en open[i].
            proceeds = units * fill_price * (1.0 - commission)
            ret_pct = (proceeds / entry_cost - 1.0) * 100.0
            trades.append(
                Trade(
                    entry_index=entry_index,
                    entry_price=entry_price,
                    exit_index=i,
                    exit_price=fill_price,
                    return_pct=ret_pct,
                )
            )
            cash = proceeds
            units = 0.0
            pos = 0

        # Marca a close[i]: cash si flat, valor de las units si long.
        equity_curve.append(cash + units * closes[i])

    return trades, equity_curve


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    """Magnitud (>= 0) del peor drawdown pico-a-valle de la curva de equity, en %."""
    peak = float("-inf")
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd * 100.0


def backtest_df(
    df: pd.DataFrame,
    symbol: str,
    interval: str,
    strategy: str,
    *,
    commission: float = COMMISSION_TAKER,
    _signal_override: pd.Series | None = None,
    **params: float,
) -> BacktestResult:
    """Corre un backtest sobre un DataFrame de klines y construye el ``BacktestResult``.

    ``_signal_override`` es un atajo de tests para inyectar una señal explícita (no se usa
    en producción). ``params`` son los parámetros de la estrategia (fast/slow/low/high/n).
    """
    if strategy not in STRATEGIES:
        raise ValueError(
            f"strategy desconocida: {strategy!r}. Válidas: {sorted(STRATEGIES)}"
        )

    n = len(df)
    if n < 2:
        # Muestra insuficiente para ejecutar un solo fill: todo en cero, honesto.
        return BacktestResult(
            symbol=symbol, interval=interval, strategy=strategy,
            total_return_pct=0.0, buy_hold_return_pct=0.0, n_trades=0,
            win_rate=0.0, max_drawdown_pct=0.0, disclaimer=DISCLAIMER,
        )

    signal = _signal_override if _signal_override is not None else STRATEGIES[strategy](df, **params)
    trades, equity_curve = simulate(df, signal, commission=commission)

    total_return_pct = (equity_curve[-1] - 1.0) * 100.0
    wins = sum(1 for t in trades if t.return_pct > 0.0)
    win_rate = (wins / len(trades)) if trades else 0.0
    max_dd = _max_drawdown_pct(equity_curve)

    first_open = float(df["open"].iloc[1])  # primer open ejecutable
    last_close = float(df["close"].iloc[-1])
    buy_hold = (last_close / first_open - 1.0) * 100.0 if first_open > 0 else 0.0

    return BacktestResult(
        symbol=symbol,
        interval=interval,
        strategy=strategy,
        total_return_pct=total_return_pct,
        buy_hold_return_pct=buy_hold,
        n_trades=len(trades),
        win_rate=win_rate,
        max_drawdown_pct=max_dd,
        disclaimer=DISCLAIMER,
    )
