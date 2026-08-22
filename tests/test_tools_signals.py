"""Tests de las tools de capa 4 (plan Task 3, spec §6) con capa 2/3 mockeadas.

``generate_signal_tool`` arma inputs reales desde klines (capa 2) + sentiment (capa 3) y
delega en el engine puro; ``scan_signals`` corre varias y rankea por score. Acá mockeamos
el ``client`` de Binance (klines) y la función de sentiment, para verificar el wiring y el
ranking sin red. Determinista.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from kainext_binance_mcp.models import SentimentResult, Signal
from kainext_binance_mcp.signals import common
from kainext_binance_mcp.tools import signals as sig_tools


def _binance_klines(n: int, *, slope: float) -> list[list[Any]]:
    """Velas sintéticas con una tendencia controlada por ``slope`` (positivo = alcista)."""
    rows: list[list[Any]] = []
    base = 1717000000000
    for i in range(n):
        price = 100.0 + slope * i
        rows.append(
            [
                base + i * 3600000,
                f"{price:.2f}", f"{price + 1:.2f}", f"{price - 1:.2f}",
                f"{price:.2f}", "10.0",
                base + i * 3600000 + 3599999,
                "1000.0", 50, "5.0", "500.0", "0",
            ]
        )
    return rows


def _sentiment(score: float) -> SentimentResult:
    return SentimentResult(
        asset="BTC", window_hours=24, score=score, n_items=3, sample=[], disclaimer="crudo"
    )


# --------------------------------------------------------------------------- #
# generate_signal_tool
# --------------------------------------------------------------------------- #

def test_generate_signal_tool_returns_signal_uptrend() -> None:
    client = MagicMock()
    client.get_klines.return_value = _binance_klines(60, slope=1.0)  # alcista sostenida
    sig = sig_tools.generate_signal_tool(
        client, "BTCUSDT", "1h", _sentiment_fn=lambda asset, **_: _sentiment(0.5)
    )
    assert isinstance(sig, Signal)
    assert sig.symbol == "BTCUSDT"
    assert sig.interval == "1h"
    assert -1.0 <= sig.score <= 1.0
    assert len(sig.factors) == 5
    assert sig.disclaimer
    # Tendencia alcista clara → score positivo → long, con stop<price<target.
    assert sig.direction == "long"
    assert sig.suggested_stop is not None and sig.suggested_target is not None
    assert sig.suggested_stop < sig.price < sig.suggested_target
    assert isinstance(sig.price, Decimal)


def test_generate_signal_tool_passes_sentiment_to_engine() -> None:
    client = MagicMock()
    client.get_klines.return_value = _binance_klines(60, slope=0.0)  # plano: factores ~neutros
    sig = sig_tools.generate_signal_tool(
        client, "BTCUSDT", "1h", _sentiment_fn=lambda asset, **_: _sentiment(0.9)
    )
    sent = next(f for f in sig.factors if f.name == "sentiment")
    assert sent.value == pytest.approx(0.9)


def test_generate_signal_tool_detects_base_asset() -> None:
    client = MagicMock()
    client.get_klines.return_value = _binance_klines(60, slope=1.0)
    seen: dict[str, str] = {}

    def fake_sentiment(asset: str, **_: Any) -> SentimentResult:
        seen["asset"] = asset
        return _sentiment(0.0)

    sig_tools.generate_signal_tool(client, "ETHUSDT", "1h", _sentiment_fn=fake_sentiment)
    assert seen["asset"] == "ETH"  # base derivada del símbolo (strip de la quote USDT)


def test_generate_signal_tool_invalid_interval_raises() -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="interval"):
        sig_tools.generate_signal_tool(
            client, "BTCUSDT", "13h", _sentiment_fn=lambda asset, **_: _sentiment(0.0)
        )
    client.get_klines.assert_not_called()


def test_generate_signal_tool_forwards_knobs() -> None:
    client = MagicMock()
    client.get_klines.return_value = _binance_klines(60, slope=1.0)
    # threshold altísimo → aunque sea alcista, cae en hold (sin niveles).
    sig = sig_tools.generate_signal_tool(
        client, "BTCUSDT", "1h", threshold=0.99,
        _sentiment_fn=lambda asset, **_: _sentiment(0.0),
    )
    assert sig.direction == "hold"
    assert sig.suggested_stop is None


def test_generate_signal_tool_sentiment_failure_degrades_to_neutral() -> None:
    # Si la capa 3 falla (red), el sentiment se degrada a 0.0 (no rompe la señal técnica).
    client = MagicMock()
    client.get_klines.return_value = _binance_klines(60, slope=1.0)

    def boom(asset: str, **_: Any) -> SentimentResult:
        raise RuntimeError("RSS caído")

    sig = sig_tools.generate_signal_tool(client, "BTCUSDT", "1h", _sentiment_fn=boom)
    sent = next(f for f in sig.factors if f.name == "sentiment")
    assert sent.value == 0.0
    assert isinstance(sig, Signal)


# --------------------------------------------------------------------------- #
# scan_signals
# --------------------------------------------------------------------------- #

def test_scan_signals_ranks_by_score_desc() -> None:
    client = MagicMock()

    def klines_by_symbol(symbol: str, interval: str, limit: int) -> list[list[Any]]:
        # BTC alcista fuerte, ETH plano, SOL bajista.
        slope = {"BTCUSDT": 2.0, "ETHUSDT": 0.0, "SOLUSDT": -2.0}[symbol]
        return _binance_klines(60, slope=slope)

    client.get_klines.side_effect = klines_by_symbol
    out = sig_tools.scan_signals(
        client, ["ETHUSDT", "SOLUSDT", "BTCUSDT"], "1h",
        _sentiment_fn=lambda asset, **_: _sentiment(0.0),
    )
    assert [s.symbol for s in out] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    # Orden descendente por score.
    assert out[0].score >= out[1].score >= out[2].score
    assert out[0].direction == "long"
    assert out[-1].direction == "avoid"


def test_scan_signals_empty_list() -> None:
    client = MagicMock()
    out = sig_tools.scan_signals(
        client, [], "1h", _sentiment_fn=lambda asset, **_: _sentiment(0.0)
    )
    assert out == []
    client.get_klines.assert_not_called()


# --------------------------------------------------------------------------- #
# binance_backtest_signal (capa 4 backtest — read-only)
# --------------------------------------------------------------------------- #

def test_binance_backtest_signal_wires_klines_to_backtest() -> None:
    from kainext_binance_mcp.models import BacktestResult

    client = MagicMock()
    client.get_klines.return_value = _binance_klines(140, slope=1.0)  # alcista
    res = sig_tools.binance_backtest_signal(client, "BTCUSDT", "1h", limit=140)
    assert isinstance(res, BacktestResult)
    assert res.symbol == "BTCUSDT"
    assert res.interval == "1h"
    # Etiqueta honesta (no es una estrategia de capa 2) y exclusión de sentiment explícita.
    assert res.strategy != "ema_cross"
    assert "sentiment" in res.disclaimer.lower()
    client.get_klines.assert_called_once()


def test_binance_backtest_signal_invalid_interval_raises() -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="interval"):
        sig_tools.binance_backtest_signal(client, "BTCUSDT", "13h")
    client.get_klines.assert_not_called()


def test_binance_backtest_signal_forwards_knobs() -> None:
    client = MagicMock()
    client.get_klines.return_value = _binance_klines(140, slope=1.0)
    # threshold altísimo → la señal nunca entra long → 0 trades.
    res = sig_tools.binance_backtest_signal(
        client, "BTCUSDT", "1h", limit=140, threshold=0.99
    )
    assert res.n_trades == 0


# --------------------------------------------------------------------------- #
# Helpers: fallbacks honestos (sin red)
# --------------------------------------------------------------------------- #

def test_base_asset_known_quotes() -> None:
    assert sig_tools._base_asset("BTCUSDT") == "BTC"
    assert sig_tools._base_asset("ETHBTC") == "ETH"
    assert sig_tools._base_asset("solusdt") == "SOL"  # case-insensitive


def test_base_asset_unknown_quote_returns_whole_symbol() -> None:
    # Símbolo sin un quote conocido como sufijo → devuelve el símbolo completo (mejor pedir
    # sentiment de algo que de nada).
    assert sig_tools._base_asset("WEIRDPAIR") == "WEIRDPAIR"


def test_last_valid_all_nan_returns_default() -> None:
    s = pd.Series([float("nan"), float("nan")])
    assert common.last_valid(s) == 0.0
    assert common.last_valid(s, default=50.0) == 50.0


def test_bb_position_collapsed_bands_is_neutral() -> None:
    # Bandas colapsadas (serie plana) → posición neutra 0.5.
    assert common.bb_position(100.0, 100.0, 100.0) == 0.5
