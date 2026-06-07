"""Tests del harness de backtest (plan Task 4, spec §5).

El foco es la honestidad: SIN LOOKAHEAD. La señal se decide con datos hasta el cierre
de la vela ``t`` y la ejecución simulada usa el ``open`` de ``t+1``. Hay un test que
FALLA si la implementación ejecuta en el ``close`` de ``t`` (lookahead), y otro que
verifica que cambiar el ``close`` de la última vela no altera trades ya cerrados.
"""
from __future__ import annotations

import pandas as pd
import pytest

from kainext_binance_mcp.backtest import (
    COMMISSION_TAKER,
    STRATEGIES,
    backtest_df,
    ema_cross,
    rsi_threshold,
    simulate,
)
from kainext_binance_mcp.models import BacktestResult


def _df(rows: list[dict[str, float]]) -> pd.DataFrame:
    """Construye un DataFrame OHLC (más volumen dummy) como el de fetch_klines."""
    n = len(rows)
    return pd.DataFrame(
        {
            "open_time": list(range(n)),
            "open": [r["open"] for r in rows],
            "high": [r.get("high", max(r["open"], r["close"])) for r in rows],
            "low": [r.get("low", min(r["open"], r["close"])) for r in rows],
            "close": [r["close"] for r in rows],
            "volume": [1.0] * n,
            "close_time": list(range(n)),
        }
    )


# --------------------------------------------------------------------------- #
# Anti-lookahead (CRÍTICO)
# --------------------------------------------------------------------------- #

def test_anti_lookahead_fills_at_next_open_not_close_t() -> None:
    """La entrada de un trade DEBE ser el ``open`` de ``t+1``, nunca el ``close`` de ``t``.

    Construimos una señal que pide estar long durante la vela 2 (signal[1]=1, signal[2]=0).
    El cierre de la vela 1 (close[1]=80) y el open de la vela 2 (open[2]=100) DIVERGEN a
    propósito: si la implementación tuviese lookahead y entrara al close de t=1 (80), el
    precio de entrada sería 80; sin lookahead entra al open de t+1=2 (100). Verificamos
    que el precio de entrada del trade es 100 (open de t+1), no 80 (close de t).
    """
    df = _df(
        [
            {"open": 50.0, "close": 60.0},   # bar 0 — signal[0]=0
            {"open": 70.0, "close": 80.0},   # bar 1 — signal[1]=1 => entrar en open[2]
            {"open": 100.0, "close": 110.0}, # bar 2 — signal[2]=0 => salir en open[3]
            {"open": 130.0, "close": 140.0}, # bar 3 — fill de salida en open[3]=130
        ]
    )
    signal = pd.Series([0, 1, 0, 0], index=df.index)
    trades, _equity = simulate(df, signal)

    assert len(trades) == 1
    t = trades[0]
    # Entrada al OPEN de t+1 (vela 2 = 100), NO al close de t=1 (80).
    assert t.entry_price == 100.0
    assert t.entry_price != 80.0
    assert t.entry_index == 2
    # Salida al OPEN de t+1 (vela 3 = 130), NO al close de t=2 (110).
    assert t.exit_price == 130.0
    assert t.exit_index == 3


def test_changing_last_close_does_not_alter_closed_trades() -> None:
    """Cambiar el ``close`` de la ÚLTIMA vela no puede mover un trade ya cerrado.

    La última vela sólo podría generar una señal cuya ejecución sería en ``open[last+1]``,
    que no existe. Por tanto no puede crear ni modificar fills previos.
    """
    rows = [
        {"open": 50.0, "close": 60.0},
        {"open": 70.0, "close": 80.0},
        {"open": 100.0, "close": 110.0},
        {"open": 130.0, "close": 140.0},
        {"open": 160.0, "close": 170.0},
    ]
    signal = pd.Series([0, 1, 0, 0, 0])

    trades_a, _ = simulate(_df(rows), signal)

    rows_mut = [dict(r) for r in rows]
    rows_mut[-1]["close"] = 9999.0  # cambio radical en el close de la última vela
    trades_b, _ = simulate(_df(rows_mut), signal)

    assert len(trades_a) == len(trades_b) == 1
    assert trades_a[0].entry_price == trades_b[0].entry_price
    assert trades_a[0].exit_price == trades_b[0].exit_price
    assert trades_a[0].return_pct == trades_b[0].return_pct


def test_open_position_at_end_not_a_closed_trade() -> None:
    """Si la señal queda long al final, no hay fill de salida: no es un trade cerrado."""
    df = _df(
        [
            {"open": 10.0, "close": 11.0},
            {"open": 12.0, "close": 13.0},  # signal[1]=1 => entra en open[2]
            {"open": 14.0, "close": 15.0},  # sigue long
        ]
    )
    signal = pd.Series([0, 1, 1], index=df.index)
    trades, _ = simulate(df, signal)
    assert trades == []  # entrada en open[2]=14 pero nunca sale => no es trade cerrado


# --------------------------------------------------------------------------- #
# Métricas con serie sintética de resultado conocido (calculado a mano)
# --------------------------------------------------------------------------- #

def test_metrics_two_trades_known_result() -> None:
    """Dos trades calculados a mano, con comisión taker 0.1% por lado.

    Trade 1: entra open[1]=100, sale open[3]=120.
    Trade 2: entra open[5]=100, sale open[7]=90.
    Comisión f=0.001 por lado. Retorno neto por trade:
      (exit/entry)*(1-f)^2 - 1.
      T1: 1.20*(0.999)^2 - 1 = 1.20*0.998001 - 1 = 0.1976012  => +19.76012%
      T2: 0.90*(0.999)^2 - 1 = 0.90*0.998001 - 1 = -0.1018009 => -10.18009%
    total compuesto: (1+0.1976012)*(1-0.1018009) - 1 = 1.1976012*0.8981991 - 1
      = 0.075682... => +7.5682% (aprox). win_rate = 1/2 = 0.5. n_trades=2.
    """
    df = _df(
        [
            {"open": 90.0, "close": 95.0},    # 0
            {"open": 100.0, "close": 105.0},  # 1 -> T1 entry fill
            {"open": 110.0, "close": 108.0},  # 2
            {"open": 120.0, "close": 122.0},  # 3 -> T1 exit fill
            {"open": 121.0, "close": 119.0},  # 4
            {"open": 100.0, "close": 101.0},  # 5 -> T2 entry fill
            {"open": 95.0, "close": 93.0},    # 6
            {"open": 90.0, "close": 88.0},    # 7 -> T2 exit fill
            {"open": 89.0, "close": 87.0},    # 8
        ]
    )
    # signal[t] decide la posición a mantener entrando en open[t+1].
    # Queremos: entra en open[1] (signal[0]=1), sale en open[3] (signal[2]=0),
    #           entra en open[5] (signal[4]=1), sale en open[7] (signal[6]=0).
    signal = pd.Series([1, 1, 0, 0, 1, 1, 0, 0, 0], index=df.index)
    trades, _ = simulate(df, signal)

    assert len(trades) == 2
    assert trades[0].entry_index == 1 and trades[0].entry_price == 100.0
    assert trades[0].exit_index == 3 and trades[0].exit_price == 120.0
    assert trades[1].entry_index == 5 and trades[1].entry_price == 100.0
    assert trades[1].exit_index == 7 and trades[1].exit_price == 90.0

    f = COMMISSION_TAKER
    r1 = 1.20 * (1 - f) ** 2 - 1
    r2 = 0.90 * (1 - f) ** 2 - 1
    assert trades[0].return_pct == pytest.approx(r1 * 100, abs=1e-9)
    assert trades[1].return_pct == pytest.approx(r2 * 100, abs=1e-9)

    res = backtest_df(df, "TESTUSDT", "1h", "ema_cross", _signal_override=signal)
    expected_total = ((1 + r1) * (1 + r2) - 1) * 100
    assert res.total_return_pct == pytest.approx(expected_total, abs=1e-9)
    assert res.n_trades == 2
    assert res.win_rate == pytest.approx(0.5, abs=1e-9)


def test_buy_hold_benchmark() -> None:
    """buy&hold = entrar al primer open ejecutable (open[1]) y marcar al último close."""
    df = _df(
        [
            {"open": 100.0, "close": 100.0},
            {"open": 100.0, "close": 100.0},  # open[1]=100
            {"open": 110.0, "close": 150.0},  # close[-1]=150
        ]
    )
    signal = pd.Series([0, 0, 0], index=df.index)  # estrategia flat
    res = backtest_df(df, "X", "1h", "ema_cross", _signal_override=signal)
    # (150/100 - 1)*100 = 50%
    assert res.buy_hold_return_pct == pytest.approx(50.0, abs=1e-9)
    # Estrategia flat: 0 trades, 0% retorno, 0 drawdown.
    assert res.n_trades == 0
    assert res.total_return_pct == pytest.approx(0.0, abs=1e-9)
    assert res.win_rate == 0.0
    assert res.max_drawdown_pct == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_known() -> None:
    """Drawdown de una curva de equity conocida.

    Long todo el rango: entra open[1]=100, mantiene; equity marca a close.
    closes (marcando mientras long): pico y caída. Verificamos magnitud del peor drawdown.
    """
    df = _df(
        [
            {"open": 100.0, "close": 100.0},
            {"open": 100.0, "close": 100.0},  # entra open[1]=100
            {"open": 120.0, "close": 200.0},  # equity ~2x (pico)
            {"open": 150.0, "close": 100.0},  # equity vuelve a ~1x (caída 50% desde pico)
            {"open": 100.0, "close": 100.0},
        ]
    )
    signal = pd.Series([1, 1, 1, 1, 1], index=df.index)
    res = backtest_df(df, "X", "1h", "ema_cross", _signal_override=signal)
    # Pico marcado a 200, valle a 100 => drawdown 50% (sin contar comisión, ~ aprox).
    assert res.max_drawdown_pct == pytest.approx(50.0, abs=2.0)
    assert res.max_drawdown_pct >= 0.0


def test_disclaimer_present() -> None:
    df = _df([{"open": 1.0, "close": 1.0}, {"open": 1.0, "close": 1.0}])
    res = backtest_df(df, "X", "1h", "ema_cross", fast=1, slow=2)
    assert isinstance(res, BacktestResult)
    assert res.disclaimer
    assert "backtest" in res.disclaimer.lower()
    assert "slippage" in res.disclaimer.lower()


# --------------------------------------------------------------------------- #
# Estrategias
# --------------------------------------------------------------------------- #

def test_ema_cross_monotonic_up_profits() -> None:
    """Serie monótona creciente: ema_cross queda long y gana (> 0)."""
    closes = [float(x) for x in range(10, 60)]  # 10..59
    df = _df([{"open": c, "close": c} for c in closes])
    res = backtest_df(df, "X", "1h", "ema_cross", fast=2, slow=5)
    assert res.total_return_pct > 0.0


def test_ema_cross_signal_shape() -> None:
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    df = _df([{"open": c, "close": c} for c in closes])
    sig = ema_cross(df, fast=2, slow=4)
    assert set(sig.unique()) <= {0, 1}
    assert len(sig) == len(df)
    assert sig.iloc[-1] == 1  # fast por encima de slow en tendencia alcista


def test_rsi_threshold_signal_shape() -> None:
    # Serie con caída fuerte (RSI bajo => compra) y luego subida (RSI alto => vende).
    down = [100.0 - i for i in range(20)]
    up = [80.0 + 2 * i for i in range(20)]
    closes = down + up
    df = _df([{"open": c, "close": c} for c in closes])
    sig = rsi_threshold(df, low=30.0, high=70.0)
    assert set(sig.unique()) <= {0, 1}
    assert len(sig) == len(df)


def test_strategies_registry_contains_both() -> None:
    assert set(STRATEGIES.keys()) == {"ema_cross", "rsi_threshold"}


def test_ema_cross_invalid_params_raise() -> None:
    df = _df([{"open": 1.0, "close": 1.0}, {"open": 1.0, "close": 1.0}])
    with pytest.raises(ValueError, match="> 0"):
        ema_cross(df, fast=0, slow=5)
    with pytest.raises(ValueError, match="> 0"):
        ema_cross(df, fast=2, slow=-1)
    with pytest.raises(ValueError, match="fast debe ser < slow"):
        ema_cross(df, fast=5, slow=5)


def test_rsi_threshold_invalid_bounds_raise() -> None:
    df = _df([{"open": 1.0, "close": 1.0}, {"open": 1.0, "close": 1.0}])
    with pytest.raises(ValueError, match="low < high"):
        rsi_threshold(df, low=70.0, high=30.0)
    with pytest.raises(ValueError, match="low < high"):
        rsi_threshold(df, low=-1.0, high=70.0)


def test_backtest_df_unknown_strategy_raises() -> None:
    df = _df([{"open": 1.0, "close": 1.0}, {"open": 1.0, "close": 1.0}])
    with pytest.raises(ValueError, match="strategy"):
        backtest_df(df, "X", "1h", "nope")


def test_backtest_df_too_short_returns_zeros() -> None:
    df = _df([{"open": 1.0, "close": 1.0}])  # una sola vela
    res = backtest_df(df, "X", "1h", "ema_cross")
    assert res.n_trades == 0
    assert res.total_return_pct == 0.0
    assert res.buy_hold_return_pct == 0.0
    assert res.max_drawdown_pct == 0.0


def test_rsi_threshold_via_backtest_df() -> None:
    down = [100.0 - i for i in range(20)]
    up = [80.0 + 2 * i for i in range(20)]
    closes = down + up
    df = _df([{"open": c, "close": c} for c in closes])
    res = backtest_df(df, "X", "1h", "rsi_threshold", low=30.0, high=70.0)
    assert isinstance(res, BacktestResult)
    assert res.strategy == "rsi_threshold"
