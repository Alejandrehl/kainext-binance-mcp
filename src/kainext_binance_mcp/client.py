"""Wrapper de python-binance (spec §4.5)."""
from __future__ import annotations
import time
from binance.client import Client
from kainext_binance_mcp.config import Settings


def make_client(settings: Settings) -> Client:
    client = Client(settings.api_key, settings.api_secret, testnet=settings.is_testnet)
    # Sync de offset de tiempo para evitar -1021 por clock drift.
    server_time = client.get_server_time()["serverTime"]
    # python-binance maneja el offset internamente al setear timestamp_offset:
    client.timestamp_offset = server_time - _now_ms()
    return client


def _now_ms() -> int:
    return int(time.time() * 1000)
