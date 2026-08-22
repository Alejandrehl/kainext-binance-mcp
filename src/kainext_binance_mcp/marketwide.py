"""Capa 5 — estructura del mercado completo desde fuentes públicas gratuitas.

Fuentes (todas verificadas, sin API key): alternative.me (Fear & Greed), CoinGecko
(/global y /coins/bitcoin), mempool.space (fees, hashrate). Independientes de
BINANCE_ENV: describen SIEMPRE el mercado real.

Presupuesto de latencia: timeout de 5s POR fuente (peor caso ~4 requests ≈ 20s, bajo el
timeout típico de tool-call). Cache TTL ≥300s (CoinGecko free tier ratelimitea agresivo).
Degradación POR FUENTE: un bloque caído → None + nota; la tool nunca se cae entera.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import requests

from kainext_binance_mcp.models import MarketStructure

DISCLAIMER = (
    "Market-wide context from free public sources; any block can be None if its source "
    "is down (see notes). Sentiment/dominance are thermometers, not forecasts. "
    "Interpret with kb://glossary and kb://frameworks/cycle-analysis. Not financial advice."
)

_TIMEOUT_S = 5.0
CACHE_TTL_SECONDS = 300.0  # >= 300: CoinGecko free tier tolera ~10-30 req/min

_FNG_URL = "https://api.alternative.me/fng/"
_CG_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
_CG_BTC_URL = (
    "https://api.coingecko.com/api/v3/coins/bitcoin"
    "?localization=false&tickers=false&market_data=true"
    "&community_data=false&developer_data=false&sparkline=false"
)
_MEMPOOL_FEES_URL = "https://mempool.space/api/v1/fees/recommended"
_MEMPOOL_HASHRATE_URL = "https://mempool.space/api/v1/mining/hashrate/3d"


class TtlCache:
    """Cache TTL por clave con clock inyectable (mismo patrón que news.fetch.NewsCache)."""

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self.clock = clock
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        hit = self._entries.get(key)
        if hit is None:
            return None
        ts, value = hit
        if self.clock() - ts >= self.ttl:
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        self._entries[key] = (self.clock(), value)


_MODULE_CACHE = TtlCache()


def _get_json(url: str) -> Any:
    resp = requests.get(url, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def get_market_structure(*, _cache: TtlCache | None = None,
                         _get: Callable[[str], Any] | None = None,
                         _now_ms: Callable[[], int] | None = None) -> MarketStructure:
    """Agrega F&G + dominancia/mcap + ATH BTC + fees/hashrate, con degradación por fuente."""
    cache = _cache if _cache is not None else _MODULE_CACHE
    get = _get if _get is not None else _get_json
    now_ms = _now_ms if _now_ms is not None else (lambda: int(time.time() * 1000))

    cached = cache.get("market_structure")
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    notes: list[str] = []

    fear_greed: int | None = None
    fear_greed_label: str | None = None
    fear_greed_week: list[int] = []
    try:
        fng = get(_FNG_URL + "?limit=7")["data"]
        fear_greed = int(fng[0]["value"])
        fear_greed_label = str(fng[0]["value_classification"])
        fear_greed_week = [int(d["value"]) for d in fng]
    except Exception as e:  # noqa: BLE001 — degradación por fuente, nunca tumba la tool
        notes.append(f"fear_greed unavailable: {type(e).__name__}")

    dominance: float | None = None
    mcap: float | None = None
    try:
        g = get(_CG_GLOBAL_URL)["data"]
        dominance = float(g["market_cap_percentage"]["btc"])
        mcap = float(g["total_market_cap"]["usd"])
    except Exception as e:  # noqa: BLE001
        notes.append(f"coingecko_global unavailable: {type(e).__name__}")

    ath: Decimal | None = None
    ath_date: str | None = None
    ath_change: float | None = None
    try:
        md = get(_CG_BTC_URL)["market_data"]
        ath = Decimal(str(md["ath"]["usd"]))
        ath_date = str(md["ath_date"]["usd"])[:10]
        ath_change = float(md["ath_change_percentage"]["usd"])
    except Exception as e:  # noqa: BLE001
        notes.append(f"coingecko_btc_ath unavailable: {type(e).__name__}")

    fee_fast: int | None = None
    try:
        fee_fast = int(get(_MEMPOOL_FEES_URL)["fastestFee"])
    except Exception as e:  # noqa: BLE001
        notes.append(f"mempool_fees unavailable: {type(e).__name__}")

    hashrate_ehs: float | None = None
    try:
        rates = get(_MEMPOOL_HASHRATE_URL)["hashrates"]
        if rates:
            hashrate_ehs = float(rates[-1]["avgHashrate"]) / 1e18  # H/s → EH/s
    except Exception as e:  # noqa: BLE001
        notes.append(f"mempool_hashrate unavailable: {type(e).__name__}")

    result = MarketStructure(
        fear_greed=fear_greed, fear_greed_label=fear_greed_label,
        fear_greed_week=fear_greed_week,
        btc_dominance_pct=dominance, total_market_cap_usd=mcap,
        btc_ath_usd=ath, btc_ath_date=ath_date, btc_ath_change_pct=ath_change,
        mempool_fee_fast_sat_vb=fee_fast, hashrate_avg_ehs=hashrate_ehs,
        notes=notes, as_of=now_ms(), disclaimer=DISCLAIMER,
    )
    cache.put("market_structure", result)
    return result
