"""Watchdog v1.2: parse, evaluación por cruce, anti-spam, notify, estado."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kainext_binance_mcp.config import ConfigError
from kainext_binance_mcp.watch import (
    Trigger,
    evaluate,
    fetch_value,
    is_met,
    load_config,
    load_state,
    notify,
    parse_config,
    save_state,
)

_BASE = {"interval_seconds": 60,
         "price": [{"symbol": "BTCUSDT", "above": 98000}],
         "fear_greed": [{"below": 15}]}


def test_parse_config_ok_and_keys() -> None:
    interval, webhook, ts = parse_config(dict(_BASE))
    assert interval == 60 and webhook is None and len(ts) == 2
    assert ts[0].key == "price:BTCUSDT:above:98000"


@pytest.mark.parametrize("bad", [
    {"interval_seconds": 30, **{k: v for k, v in _BASE.items() if k != "interval_seconds"}},
    {"interval_seconds": 60},                                            # sin triggers
    {"interval_seconds": 60, "price": [{"above": 1}]},                   # sin symbol
    {"interval_seconds": 60, "price": [{"symbol": "b!", "above": 1}]},   # symbol inválido
    {"interval_seconds": 60, "price": [{"symbol": "BTCUSDT"}]},          # sin op
    {"interval_seconds": 60, "price": [{"symbol": "BTCUSDT", "above": 1, "below": 2}]},
    {"interval_seconds": 60, "funding": [{"symbol": "BTCUSDT", "above": 1}]},
    {"interval_seconds": 60, "webhook_url": "http://insecure",
     "price": [{"symbol": "BTCUSDT", "above": 1}]},
])
def test_parse_config_rejects(bad: dict) -> None:
    with pytest.raises(ConfigError):
        parse_config(bad)


def test_is_met_ops() -> None:
    assert is_met(Trigger("price", "X", "above", 10), 11)
    assert not is_met(Trigger("price", "X", "above", 10), 10)
    assert is_met(Trigger("price", "X", "below", 10), 9)
    assert is_met(Trigger("funding", "X", "abs_above", 0.0005), -0.001)


def test_fetch_value_routes_by_kind() -> None:
    def get(url, params=None):
        if "ticker/price" in url:
            return {"price": "77000"}
        if "klines" in url:
            return [[0, "1", "2", "3", "76000", "5"], [1, "1", "2", "3", "99999", "5"]]
        if "premiumIndex" in url:
            return {"lastFundingRate": "0.0007"}
        return {"data": [{"value": "12"}]}

    assert fetch_value(Trigger("price", "BTCUSDT", "above", 1), get) == 77000
    # daily_close usa la vela COMPLETADA ([-2]), no la en curso
    assert fetch_value(Trigger("daily_close", "BTCUSDT", "above", 1), get) == 76000
    assert fetch_value(Trigger("funding", "BTCUSDT", "abs_above", 1), get) == 0.0007
    assert fetch_value(Trigger("fear_greed", None, "below", 1), get) == 12


def test_evaluate_fires_on_crossing_only() -> None:
    t = Trigger("price", "BTCUSDT", "above", 100)
    prices = {"v": 90.0}

    def get(url, params=None):
        return {"price": str(prices["v"])}

    fired, st = evaluate([t], {}, get)
    assert fired == []                       # bajo el umbral: nada
    prices["v"] = 101.0
    fired, st = evaluate([t], st, get)
    assert len(fired) == 1                   # CRUZÓ: dispara
    fired, st = evaluate([t], st, get)
    assert fired == []                       # sigue arriba: anti-spam
    prices["v"] = 99.0
    fired, st = evaluate([t], st, get)
    assert fired == []                       # se limpia: re-arma sin disparar
    prices["v"] = 102.0
    fired, st = evaluate([t], st, get)
    assert len(fired) == 1                   # segundo cruce: dispara de nuevo


def test_evaluate_source_down_keeps_state() -> None:
    t = Trigger("price", "BTCUSDT", "above", 100)

    def boom(url, params=None):
        raise OSError("down")

    fired, st = evaluate([t], {t.key: True}, boom)
    assert fired == [] and st[t.key] is True  # ni fantasma ni re-arme falso


def test_notify_webhook_and_never_raises() -> None:
    calls: list[tuple] = []
    notify("msg", "https://x/hook", _run=lambda *a, **k: None,
           _post=lambda url, json, timeout: calls.append((url, json)))
    assert calls and calls[0][1]["message"] == "msg"

    def bad_post(url, json, timeout):
        raise OSError("down")

    notify("msg", "https://x/hook", _run=lambda *a, **k: None, _post=bad_post)  # no lanza


def test_state_roundtrip(tmp_path: Path) -> None:
    cfg = tmp_path / "watch.toml"
    save_state(cfg, {"a": True, "b": False})
    assert load_state(cfg) == {"a": True, "b": False}
    assert json.loads((tmp_path / "state.json").read_text())["a"] is True
    fresh = tmp_path / "otra-carpeta"
    fresh.mkdir()
    assert load_state(fresh / "watch.toml") == {}  # sin estado = desarmado


def test_load_config_missing_and_invalid(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("interval_seconds = [")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(bad)
