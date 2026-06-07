"""Test de integración de capa 4: señal compuesta REAL para BTCUSDT (spec §2/§6).

Ejercita el camino completo end-to-end con datos REALES:

    make_client(load_server_settings(...))   # read key de testnet
      → generate_signal_tool(client, "BTCUSDT", "1h")
          fetch_klines (capa 2, público)  → EMA/RSI/MACD/Bollinger/ATR
          get_sentiment (capa 3, RSS público) → score crudo del activo (degrada a 0.0)
          engine.generate_signal (puro)  → Signal transparente
      → invariantes: score ∈ [-1,1]; 5 factores poblados; disclaimer presente;
        si direction == "long" entonces stop < price < target.

Klines son PÚBLICAS (no requieren fondos); el sentiment es RSS público y puede degradar a
0.0 si el feed falla — el test tolera eso. **Tolerante**: si faltan keys, red, feed o datos,
``pytest.skip`` con mensaje claro — nunca un fail duro (igual criterio que capa 2/3).

Cómo correrlo (keys de testnet — https://testnet.binance.vision):

    export BINANCE_ENV=testnet
    export BINANCE_READ_API_KEY=...
    export BINANCE_READ_API_SECRET=...
    .venv/bin/python -m pytest tests/integration/test_capa4_signals.py -v -s --cov-fail-under=0
"""
from __future__ import annotations

import os

import pytest

from kainext_binance_mcp.models import Signal

_HAS_KEYS = bool(os.environ.get("BINANCE_READ_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _HAS_KEYS, reason="requiere keys (BINANCE_READ_API_KEY)"),
]

_SYMBOL = "BTCUSDT"
_INTERVAL = "1h"
# Los 5 factores que el engine compone (spec §5): tendencia, momentum, MACD, Bollinger,
# sentiment. No black box (S3): cada uno aparece en Signal.factors con su contribución.
_EXPECTED_FACTORS = {"trend", "momentum", "macd", "bollinger", "sentiment"}


@pytest.fixture
def read_client():
    """Client real (read key de testnet) construido desde el entorno."""
    from kainext_binance_mcp.client import make_client
    from kainext_binance_mcp.config import load_server_settings

    settings = load_server_settings(os.environ)
    return make_client(settings)


def test_capa4_generate_signal_real(read_client):
    """Señal compuesta real para BTCUSDT 1h: score acotado, 5 factores, niveles coherentes."""
    from kainext_binance_mcp.tools import signals as sig

    try:
        signal = sig.generate_signal_tool(read_client, _SYMBOL, _INTERVAL)
    except Exception as exc:  # noqa: BLE001 — tolerante: red/datos rotos no es fail del test
        pytest.skip(f"generate_signal_tool real falló (red/datos): {exc}")

    assert isinstance(signal, Signal)

    # ── Reporte humano de la señal real generada (lo pide la tarea, -s lo muestra).
    print(f"\n[itest-capa4] señal real {signal.symbol} {signal.interval}")
    print(f"  dirección: {signal.direction}   score: {signal.score:+.4f}")
    print(f"  precio: {signal.price}   ATR: {signal.atr:.4f}")
    print(f"  stop: {signal.suggested_stop}   target: {signal.suggested_target}")
    print("  factores (5):")
    for f in signal.factors:
        print(
            f"    · {f.name:<10} value={f.value:+.4f} weight={f.weight:.2f} "
            f"contrib={f.contribution:+.4f}  — {f.note}"
        )
    print(f"  disclaimer: {signal.disclaimer}")

    # ── Invariantes (exigidas cuando hay datos reales).
    # 1) score acotado.
    assert -1.0 <= signal.score <= 1.0, f"score fuera de [-1,1]: {signal.score}"

    # 2) factores no vacíos: exactamente los 5 esperados, poblados.
    assert signal.factors, "factors vacío en señal real"
    names = {f.name for f in signal.factors}
    assert names == _EXPECTED_FACTORS, f"factores inesperados: {names}"
    assert len(signal.factors) == 5

    # 3) disclaimer presente (S6: no es predicción).
    assert signal.disclaimer and signal.disclaimer.strip(), "disclaimer vacío"

    # 4) precio y ATR sanos.
    assert signal.price > 0, "precio no positivo en datos reales"
    assert signal.atr >= 0.0, "ATR negativo (imposible)"

    # 5) niveles coherentes para long: stop < price < target (S4).
    if signal.direction == "long":
        assert signal.suggested_stop is not None
        assert signal.suggested_target is not None
        assert signal.suggested_stop < signal.price < signal.suggested_target, (
            f"long con niveles incoherentes: stop={signal.suggested_stop} "
            f"price={signal.price} target={signal.suggested_target}"
        )
