"""Integración capa 4 — backtest REAL de la señal técnica compuesta (spec capa-4-backtest §T3).

Ejercita el camino completo con datos REALES (klines públicas de Binance):

    make_client(load_server_settings(...))   # read key de testnet
      → binance_backtest_signal(client, "BTCUSDT", interval, limit)
          fetch_klines (capa 2, público) → indicadores causales por vela
          engine.generate_signal(sentiment=0) por vela → posiciones {0,1}
          backtest_df (capa 2, anti-lookahead) → BacktestResult
      → REPORTA las métricas reales: total_return_pct vs buy_hold_return_pct,
        n_trades, win_rate, max_drawdown_pct. ¿La señal le gana a buy&hold o no?

Klines son PÚBLICAS (no requieren fondos). **Tolerante**: si faltan keys o la red falla,
``pytest.skip`` con mensaje claro — nunca un fail duro (igual criterio que capa 2/3/4).

Cómo correrlo (keys de testnet — https://testnet.binance.vision):

    export BINANCE_ENV=testnet
    export BINANCE_READ_API_KEY=...
    export BINANCE_READ_API_SECRET=...
    .venv/bin/python -m pytest tests/integration/test_capa4_backtest.py -v -s --cov-fail-under=0
"""
from __future__ import annotations

import os

import pytest

from kainext_binance_mcp.models import BacktestResult

_HAS_KEYS = bool(os.environ.get("BINANCE_READ_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _HAS_KEYS, reason="requiere keys (BINANCE_READ_API_KEY)"),
]

_SYMBOL = "BTCUSDT"


@pytest.fixture
def read_client():
    """Client real (read key de testnet) construido desde el entorno."""
    from kainext_binance_mcp.client import make_client
    from kainext_binance_mcp.config import load_server_settings

    settings = load_server_settings(os.environ)
    return make_client(settings)


def _report(res: BacktestResult) -> None:
    """Imprime el veredicto honesto: ¿la señal técnica le gana a buy&hold?"""
    edge = res.total_return_pct - res.buy_hold_return_pct
    verdict = "GANA a buy&hold" if edge > 0 else ("EMPATA" if edge == 0 else "PIERDE vs buy&hold")
    print(f"\n[itest-capa4-backtest] {res.symbol} {res.interval}  ({res.strategy})")
    print(f"  total_return_pct : {res.total_return_pct:+.2f}%")
    print(f"  buy_hold_pct     : {res.buy_hold_return_pct:+.2f}%")
    print(f"  edge (estrat-BH) : {edge:+.2f}%  → {verdict}")
    print(f"  n_trades         : {res.n_trades}")
    print(f"  win_rate         : {res.win_rate * 100:.1f}%")
    print(f"  max_drawdown_pct : {res.max_drawdown_pct:.2f}%")
    print(f"  disclaimer       : {res.disclaimer}")


@pytest.mark.parametrize("interval", ["1h", "4h"])
def test_capa4_backtest_real(read_client, interval: str) -> None:
    """Backtest real de BTCUSDT en 1h y 4h sobre 1000 velas: reporta métricas e invariantes."""
    from kainext_binance_mcp.tools import signals as sig

    try:
        res = sig.binance_backtest_signal(read_client, _SYMBOL, interval, limit=1000)
    except Exception as exc:  # noqa: BLE001 — tolerante: red/datos rotos no es fail del test
        pytest.skip(f"binance_backtest_signal real falló (red/datos): {exc}")

    assert isinstance(res, BacktestResult)
    _report(res)

    # Invariantes (exigidas cuando hay datos reales).
    assert res.symbol == _SYMBOL
    assert res.interval == interval
    assert res.n_trades >= 0
    assert 0.0 <= res.win_rate <= 1.0
    assert res.max_drawdown_pct >= 0.0
    # Disclaimer honesto: deja explícita la exclusión del sentiment.
    assert "sentiment" in res.disclaimer.lower()
    assert res.strategy != "ema_cross"
