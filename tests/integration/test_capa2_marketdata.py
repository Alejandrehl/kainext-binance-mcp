"""Test de integración de capa 2 contra datos REALES de Binance (klines/ticker).

Ejercita el camino read-only de capa 2 con un client real:

    make_client(load_server_settings(...))   # read key de testnet
      → fetch_klines(client, "BTCUSDT", "1h", 100)   → DataFrame ~100 filas
      → compute_indicators(...)  para rsi/macd/ema/bollinger/atr
      → sanity-checks: RSI ∈ [0,100] (no-NaN), longitudes coherentes con las klines,
        MACD trae macd/signal/hist.
      → (opcional) get_ticker_24h(...)

Klines y ticker son endpoints PÚBLICOS de Binance: no requieren auth ni fondos. Las
keys sólo se usan para construir el client (y validar el gate de skip). Sin
``BINANCE_READ_API_KEY`` en el entorno el test SKIPEA limpio (no toca red).

Cómo correrlo (keys de testnet — https://testnet.binance.vision):

    export BINANCE_ENV=testnet
    export BINANCE_READ_API_KEY=...
    export BINANCE_READ_API_SECRET=...
    .venv/bin/python -m pytest tests/integration/test_capa2_marketdata.py -v -s
"""
from __future__ import annotations

import math
import os

import pytest

_HAS_KEYS = bool(os.environ.get("BINANCE_READ_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _HAS_KEYS, reason="requiere keys (BINANCE_READ_API_KEY)"),
]

_SYMBOL = "BTCUSDT"
_INTERVAL = "1h"
_LIMIT = 100


@pytest.fixture
def read_client():
    """Client real (read key) construido desde el entorno."""
    from kainext_binance_mcp.client import make_client
    from kainext_binance_mcp.config import load_server_settings

    settings = load_server_settings(os.environ)
    return make_client(settings)


def test_capa2_klines_and_indicators_real(read_client):
    from kainext_binance_mcp.klines import fetch_klines
    from kainext_binance_mcp.tools import marketdata as md

    # ── 1) Klines reales → DataFrame con ~100 filas y columnas estandarizadas.
    df = fetch_klines(read_client, _SYMBOL, _INTERVAL, _LIMIT)
    n = len(df)
    print(f"[itest-capa2] fetch_klines({_SYMBOL}, {_INTERVAL}, {_LIMIT}) → {n} velas")
    assert n > 0, "klines reales no devolvió ninguna vela"
    # La API devuelve hasta `limit` velas; con 100 esperamos exactamente 100 en un par
    # líquido como BTCUSDT (margen por si testnet tuviera menos histórico).
    assert n <= _LIMIT
    assert n >= 50, f"esperaba ~{_LIMIT} velas, llegaron {n}"
    assert list(df.columns) == [
        "open_time", "open", "high", "low", "close", "volume", "close_time"
    ]
    assert df["close"].notna().all(), "hay closes NaN en datos reales"
    assert (df["high"] >= df["low"]).all(), "high < low en alguna vela real"

    # ── 2) Indicadores sobre los datos reales (las 5 familias).
    result = md.compute_indicators(
        read_client, _SYMBOL, _INTERVAL,
        indicators=["rsi", "macd", "ema", "bollinger", "atr"],
        limit=_LIMIT,
    )
    ind = result.indicators
    print(f"[itest-capa2] indicadores calculados: {sorted(ind.keys())}")

    # Longitudes coherentes con las klines: cada serie alinea 1:1 con las velas.
    # (compute_indicators re-fetcha, así que comparamos contra as_of/longitud propia.)
    for name, series in ind.items():
        assert len(series) == n, (
            f"longitud de {name} ({len(series)}) != velas ({n})"
        )

    # RSI ∈ [0, 100] para los valores no-NaN (None).
    rsi_vals = [v for v in ind["rsi"] if v is not None]
    assert rsi_vals, "RSI quedó todo None (no debería con ~100 velas y n=14)"
    rsi_min, rsi_max = min(rsi_vals), max(rsi_vals)
    print(f"[itest-capa2] RSI observado: [{rsi_min:.2f}, {rsi_max:.2f}] sobre {len(rsi_vals)} pts")
    assert all(0.0 <= v <= 100.0 for v in rsi_vals), f"RSI fuera de [0,100]: {rsi_min}..{rsi_max}"

    # MACD trae macd / signal / hist, y hist ≈ macd - signal donde ambos existen.
    assert {"macd", "macd_signal", "macd_hist"} <= ind.keys()
    macd_pts = [
        (m, s, h)
        for m, s, h in zip(ind["macd"], ind["macd_signal"], ind["macd_hist"])
        if m is not None and s is not None and h is not None
    ]
    assert macd_pts, "MACD/signal/hist quedaron todos None"
    for m, s, h in macd_pts:
        assert math.isclose(h, m - s, rel_tol=1e-9, abs_tol=1e-9), (
            f"hist ({h}) != macd-signal ({m - s})"
        )

    # EMA: al menos un valor real y todos finitos.
    ema_vals = [v for v in ind["ema"] if v is not None]
    assert ema_vals and all(math.isfinite(v) for v in ema_vals)

    # Bollinger: upper >= mid >= lower donde las tres existen.
    boll_pts = [
        (u, mid, lo)
        for u, mid, lo in zip(
            ind["bollinger_upper"], ind["bollinger_mid"], ind["bollinger_lower"]
        )
        if u is not None and mid is not None and lo is not None
    ]
    assert boll_pts, "Bollinger quedó todo None"
    for u, mid, lo in boll_pts:
        assert u >= mid >= lo, f"banda inconsistente: upper={u} mid={mid} lower={lo}"

    # ATR: positivo (rango de precios real > 0) donde existe.
    atr_vals = [v for v in ind["atr"] if v is not None]
    assert atr_vals, "ATR quedó todo None"
    assert all(v >= 0.0 for v in atr_vals), "ATR negativo (imposible)"

    assert result.as_of > 0, "as_of debería ser el close_time de la última vela"


def test_capa2_ticker_24h_real(read_client):
    """Opcional: ticker 24h real (endpoint público) bien tipado."""
    from kainext_binance_mcp.tools import marketdata as md

    t = md.get_ticker_24h(read_client, _SYMBOL)
    print(
        f"[itest-capa2] ticker24h {t.symbol}: last={t.last} "
        f"change%={t.price_change_pct} high={t.high} low={t.low} vol={t.volume}"
    )
    assert t.symbol == _SYMBOL
    assert t.last > 0
    assert t.high >= t.low
    assert t.volume >= 0
