"""Capa 5: marketwide (agregador de fuentes públicas) — degradación, cache, shapes."""
from __future__ import annotations

from decimal import Decimal

from kainext_binance_mcp.marketwide import (
    CACHE_TTL_SECONDS,
    TtlCache,
    get_market_structure,
)

_FNG = {"data": [{"value": "71", "value_classification": "Greed"},
                 {"value": "62", "value_classification": "Greed"}]}
_GLOBAL = {"data": {"market_cap_percentage": {"btc": 58.3},
                    "total_market_cap": {"usd": 2.6e12}}}
_BTC = {"market_data": {"ath": {"usd": 126080}, "ath_date": {"usd": "2025-10-06T00:00:00Z"},
                        "ath_change_percentage": {"usd": -38.7}}}
_FEES = {"fastestFee": 3}
_HASH = {"hashrates": [{"timestamp": 1, "avgHashrate": 8.0e20}]}


def _fake_get(url: str):
    if "alternative.me" in url:
        return _FNG
    if "global" in url:
        return _GLOBAL
    if "coins/bitcoin" in url:
        return _BTC
    if "fees" in url:
        return _FEES
    if "hashrate" in url:
        return _HASH
    raise AssertionError(f"url inesperada {url}")


def test_aggregates_all_sources() -> None:
    ms = get_market_structure(_cache=TtlCache(), _get=_fake_get, _now_ms=lambda: 123)
    assert ms.fear_greed == 71 and ms.fear_greed_label == "Greed"
    assert ms.fear_greed_week == [71, 62]
    assert ms.btc_dominance_pct == 58.3
    assert ms.total_market_cap_usd == 2.6e12
    assert ms.btc_ath_usd == Decimal("126080") and ms.btc_ath_date == "2025-10-06"
    assert ms.mempool_fee_fast_sat_vb == 3
    assert ms.hashrate_avg_ehs == 800.0  # 8e20 H/s -> EH/s
    assert ms.notes == [] and ms.as_of == 123
    assert ms.disclaimer


def test_degrades_per_source_never_raises() -> None:
    def flaky(url: str):
        if "coingecko" in url or "coins/bitcoin" in url or "global" in url:
            raise OSError("down")
        return _fake_get(url)

    ms = get_market_structure(_cache=TtlCache(), _get=flaky, _now_ms=lambda: 1)
    assert ms.fear_greed == 71                      # lo sano sigue
    assert ms.btc_dominance_pct is None and ms.btc_ath_usd is None
    assert any("coingecko_global" in n for n in ms.notes)
    assert any("coingecko_btc_ath" in n for n in ms.notes)


def test_cache_ttl_avoids_refetch_and_respects_min() -> None:
    assert CACHE_TTL_SECONDS >= 300  # CoinGecko free tier: requisito del plan
    clock = {"t": 0.0}
    cache = TtlCache(ttl_seconds=300, clock=lambda: clock["t"])
    calls = {"n": 0}

    def counting(url: str):
        calls["n"] += 1
        return _fake_get(url)

    get_market_structure(_cache=cache, _get=counting, _now_ms=lambda: 1)
    first = calls["n"]
    get_market_structure(_cache=cache, _get=counting, _now_ms=lambda: 2)
    assert calls["n"] == first          # dentro del TTL: cero requests nuevas
    clock["t"] = 301.0
    get_market_structure(_cache=cache, _get=counting, _now_ms=lambda: 3)
    assert calls["n"] == first * 2      # expirado: re-fetch completo
