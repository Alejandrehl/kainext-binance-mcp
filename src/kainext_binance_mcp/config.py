"""Validación de variables de entorno del server (read key). Spec §4.1/§4.2a."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    api_key: str
    api_secret: str

    @property
    def is_testnet(self) -> bool:
        return self.env == "testnet"


def _require(values: Mapping[str, str], name: str) -> str:
    raw = values.get(name)
    if raw is None or raw.strip() == "":
        raise ConfigError(f"missing or empty environment variable {name}")
    if raw.strip().startswith("${") and raw.strip().endswith("}"):
        raise ConfigError(
            f"{name} arrived unexpanded ('{raw}'): check the ${{VAR}} in .mcp.json / shell"
        )
    return raw


def _load_settings(values: Mapping[str, str], key_prefix: str) -> Settings:
    """Loader único; sólo cambia el prefijo de las keys (READ para el server, TRADE
    para el confirmador — spec §4.2a/§4.2b)."""
    env = _require(values, "BINANCE_ENV").strip()
    if env not in ("testnet", "mainnet"):
        raise ConfigError(f"BINANCE_ENV must be 'testnet' or 'mainnet', not '{env}'")
    return Settings(
        env=env,
        api_key=_require(values, f"BINANCE_{key_prefix}_API_KEY"),
        api_secret=_require(values, f"BINANCE_{key_prefix}_API_SECRET"),
    )


def load_server_settings(values: Mapping[str, str]) -> Settings:
    return _load_settings(values, "READ")


def load_confirmer_settings(values: Mapping[str, str]) -> Settings:
    return _load_settings(values, "TRADE")
