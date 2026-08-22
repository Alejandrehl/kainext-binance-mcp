"""Watchdog `kainext-binance-mcp-watch` (v1.2): triggers → notificación. NUNCA ejecuta.

CERO API keys por construcción: solo endpoints públicos (spot ticker/klines, fapi
premiumIndex, alternative.me). El proceso no puede colocar ni cancelar órdenes — no
tiene credenciales ni habla con el confirmador. Notifica; la decisión es humana.

Config TOML (default ~/.config/kainext-binance-mcp/watch.toml, override --config):

    interval_seconds = 300          # >= 60
    # webhook_url = "https://..."   # opcional: POST JSON por disparo

    [[price]]
    symbol = "BTCUSDT"
    above = 98000                   # o below = ...

    [[daily_close]]                 # evalúa la última vela diaria COMPLETADA
    symbol = "BTCUSDT"
    above = 98000

    [[funding]]
    symbol = "BTCUSDT"
    abs_above = 0.0005              # |funding| sobre el umbral

    [[fear_greed]]
    above = 85                      # o below = 15

Anti-spam por CRUCE: cada trigger dispara al pasar de no-cumplido → cumplido y se
re-arma cuando la condición se limpia. Estado en state.json junto al config.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from kainext_binance_mcp.config import ConfigError
from kainext_binance_mcp.marketwide import _FNG_URL
from kainext_binance_mcp.models import validate_symbol

_TIMEOUT_S = 5.0
_MIN_INTERVAL_S = 60
_SPOT_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"
_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
_FAPI_PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

DEFAULT_CONFIG = Path.home() / ".config" / "kainext-binance-mcp" / "watch.toml"


@dataclass(frozen=True)
class Trigger:
    """Un trigger normalizado. kind ∈ {price, daily_close, funding, fear_greed}."""
    kind: str
    symbol: str | None
    op: str          # "above" | "below" | "abs_above"
    level: float

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.symbol or '-'}:{self.op}:{self.level:g}"

    def describe(self, value: float) -> str:
        where = f" {self.symbol}" if self.symbol else ""
        return f"[watch] {self.kind}{where} {self.op} {self.level:g} — current: {value:g}"


def parse_config(raw: dict[str, Any]) -> tuple[int, str | None, list[Trigger]]:
    """TOML dict → (interval, webhook_url, triggers). Config inválida = ConfigError."""
    interval = int(raw.get("interval_seconds", 300))
    if interval < _MIN_INTERVAL_S:
        raise ConfigError(f"interval_seconds must be >= {_MIN_INTERVAL_S}")
    webhook = raw.get("webhook_url")
    if webhook is not None and not str(webhook).startswith("https://"):
        raise ConfigError("webhook_url must be https://")
    triggers: list[Trigger] = []
    for kind in ("price", "daily_close", "funding", "fear_greed"):
        for entry in raw.get(kind, []):
            symbol = entry.get("symbol")
            if kind in ("price", "daily_close", "funding"):
                if not symbol:
                    raise ConfigError(f"[[{kind}]] requires symbol")
                try:
                    validate_symbol(str(symbol))
                except ValueError as e:
                    raise ConfigError(str(e)) from e
            ops = [op for op in ("above", "below", "abs_above") if op in entry]
            if len(ops) != 1:
                raise ConfigError(
                    f"[[{kind}]] needs exactly one of above/below/abs_above")
            op = ops[0]
            if kind == "funding" and op != "abs_above":
                raise ConfigError("[[funding]] uses abs_above")
            if kind in ("price", "daily_close") and op == "abs_above":
                raise ConfigError(f"[[{kind}]] uses above/below")
            if kind == "fear_greed" and op == "abs_above":
                raise ConfigError("[[fear_greed]] uses above/below")
            triggers.append(Trigger(kind=kind, symbol=symbol, op=op,
                                    level=float(entry[op])))
    if not triggers:
        raise ConfigError("no triggers configured")
    return interval, webhook, triggers


def load_config(path: Path) -> tuple[int, str | None, list[Trigger]]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"config not found: {path} (see examples/watch.example.toml)") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e
    return parse_config(raw)


def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    resp = requests.get(url, params=params, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def fetch_value(t: Trigger, get: Callable[..., Any]) -> float:
    """Valor actual del trigger desde endpoints públicos (sin keys)."""
    if t.kind == "price":
        return float(get(_SPOT_PRICE_URL, {"symbol": t.symbol})["price"])
    if t.kind == "daily_close":
        # Última vela COMPLETADA ([-2]): mismo anti-mecha que el runbook de cosecha.
        k = get(_SPOT_KLINES_URL, {"symbol": t.symbol, "interval": "1d", "limit": 2})
        return float(k[-2][4])
    if t.kind == "funding":
        return float(get(_FAPI_PREMIUM_URL, {"symbol": t.symbol})["lastFundingRate"])
    return float(get(_FNG_URL + "?limit=1")["data"][0]["value"])


def is_met(t: Trigger, value: float) -> bool:
    if t.op == "above":
        return value > t.level
    if t.op == "below":
        return value < t.level
    return abs(value) > t.level  # abs_above


def evaluate(triggers: list[Trigger], state: dict[str, bool],
             get: Callable[..., Any]) -> tuple[list[tuple[Trigger, float]], dict[str, bool]]:
    """Un ciclo: devuelve (disparos NUEVOS por cruce, estado nuevo). Fuente caída = se
    conserva el estado previo del trigger (sin disparo fantasma ni re-arme falso)."""
    fired: list[tuple[Trigger, float]] = []
    new_state = dict(state)
    for t in triggers:
        try:
            value = fetch_value(t, get)
        except Exception as e:  # noqa: BLE001 — una fuente caída no tumba el ciclo
            print(f"[watch] {t.key}: source unavailable ({type(e).__name__})",
                  file=sys.stderr, flush=True)
            continue
        met = is_met(t, value)
        if met and not state.get(t.key, False):
            fired.append((t, value))
        new_state[t.key] = met
    return fired, new_state


def notify(message: str, webhook_url: str | None = None,
           *, _run: Callable[..., Any] = subprocess.run,
           _post: Callable[..., Any] | None = None) -> None:
    """stdout siempre; notificación de escritorio best-effort; webhook opcional."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)
    try:
        if sys.platform == "darwin":
            script = f'display notification "{message[:200]}" with title "Binance MCP watch"'
            _run(["osascript", "-e", script.replace('"', "'").replace("'", '"', 2)],
                 capture_output=True, timeout=5)
        elif sys.platform.startswith("linux"):
            _run(["notify-send", "Binance MCP watch", message[:200]],
                 capture_output=True, timeout=5)
    except Exception:  # noqa: BLE001 — la notificación de escritorio es best-effort
        pass
    if webhook_url:
        post = _post if _post is not None else requests.post
        try:
            post(webhook_url, json={"source": "kainext-binance-mcp-watch",
                                    "message": message}, timeout=_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 — webhook caído no tumba el loop
            print(f"[watch] webhook failed: {type(e).__name__}", file=sys.stderr, flush=True)


def _state_path(config_path: Path) -> Path:
    return config_path.with_name("state.json")


def load_state(config_path: Path) -> dict[str, bool]:
    try:
        raw = json.loads(_state_path(config_path).read_text(encoding="utf-8"))
        return {str(k): bool(v) for k, v in raw.items()}
    except Exception:  # noqa: BLE001 — sin estado previo = todo desarmado
        return {}


def save_state(config_path: Path, state: dict[str, bool]) -> None:
    try:
        _state_path(config_path).write_text(json.dumps(state, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — best-effort (disco RO no tumba el loop)
        print(f"[watch] could not persist state: {type(e).__name__}",
              file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover — loop real
    parser = argparse.ArgumentParser(
        description="Trigger watchdog for kainext-binance-mcp. Notifies, NEVER executes.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--once", action="store_true",
                        help="run one evaluation cycle and exit (for smoke tests)")
    args = parser.parse_args(argv)
    interval, webhook, triggers = load_config(args.config)
    state = load_state(args.config)
    print(f"[watch] {len(triggers)} trigger(s), every {interval}s. No keys, no execution.",
          flush=True)
    while True:
        fired, state = evaluate(triggers, state, _get_json)
        for t, value in fired:
            notify(t.describe(value), webhook)
        save_state(args.config, state)
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    main()
