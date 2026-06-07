"""Test de integración de capa 3 contra feeds RSS REALES (CoinDesk, crypto.news).

A diferencia de capa 1/2, esto NO requiere keys: los feeds RSS son públicos. Pero la red
puede no estar disponible (CI sin egress, feed caído, rate-limit, cambio de formato), así
que es **tolerante**: si el fetch real no trae items, ``pytest.skip`` con mensaje claro —
nunca un fail duro. Lo que SÍ se exige cuando hay datos: campos presentes (title/url/
published), ``sentiment ∈ [-1, 1]`` y ``assets`` como lista.

Cómo correrlo (con red):

    .venv/bin/python -m pytest tests/integration/test_capa3_news.py -v -s --cov-fail-under=0
"""
from __future__ import annotations

import pytest

from kainext_binance_mcp.models import NewsItem
from kainext_binance_mcp.news.fetch import NewsCache, fetch_all
from kainext_binance_mcp.news.sources import CoinDeskRSS, CryptoNewsRSS, NewsSource

pytestmark = pytest.mark.integration


def _fetch_real(source: NewsSource) -> list[NewsItem]:
    """Fetch real de una fuente, sin cache (cache fresco por llamada)."""
    cache = NewsCache(ttl_seconds=0.0, clock=lambda: 0.0)
    try:
        return fetch_all([source], cache=cache)
    except Exception as exc:  # noqa: BLE001 — tolerante: red/feed roto no es fail del test
        pytest.skip(f"fetch real de {source.name} falló (red/feed): {exc}")


def _assert_item_shape(item: NewsItem) -> None:
    """Invariantes de un item real: campos presentes y tipados, sentiment y assets sanos."""
    assert isinstance(item, NewsItem)
    assert item.title, "title vacío en item real"
    assert item.url.startswith("http"), f"url no parece URL: {item.url!r}"
    assert isinstance(item.published, int) and item.published >= 0
    assert -1.0 <= item.sentiment <= 1.0, f"sentiment fuera de [-1,1]: {item.sentiment}"
    assert isinstance(item.assets, list)
    assert all(isinstance(a, str) for a in item.assets)


@pytest.mark.parametrize(
    "source_factory",
    [CoinDeskRSS, CryptoNewsRSS],
    ids=["coindesk", "crypto_news"],
)
def test_real_rss_feed_returns_well_formed_items(source_factory) -> None:
    source = source_factory()
    items = _fetch_real(source)
    if not items:
        pytest.skip(f"{source.name}: feed real trajo 0 items (red/feed cambió de formato)")

    print(f"\n[itest-capa3] {source.name}: {len(items)} items reales")
    for item in items[:3]:
        n_assets = ",".join(item.assets) or "-"
        print(f"  · ({item.sentiment:+.2f} | {n_assets}) {item.title[:80]}")

    for item in items:
        _assert_item_shape(item)


def test_real_feeds_aggregate_and_sentiment_range() -> None:
    """Agregado real de ambas fuentes: si hay items, sentiment de todos ∈ [-1,1]."""
    cache = NewsCache(ttl_seconds=0.0, clock=lambda: 0.0)
    try:
        items = fetch_all([CoinDeskRSS(), CryptoNewsRSS()], cache=cache, limit=20)
    except Exception as exc:  # noqa: BLE001 — tolerante a red
        pytest.skip(f"agregado real falló (red/feed): {exc}")

    if not items:
        pytest.skip("ambos feeds reales trajeron 0 items (red/feed)")

    print(f"\n[itest-capa3] agregado: {len(items)} items de CoinDesk+crypto.news")
    sentiments = [i.sentiment for i in items]
    print(f"  sentiment rango observado: [{min(sentiments):+.2f}, {max(sentiments):+.2f}]")
    assert all(-1.0 <= s <= 1.0 for s in sentiments)
    # orden por más reciente (fetch_all garantiza published desc).
    assert items == sorted(items, key=lambda i: i.published, reverse=True)
