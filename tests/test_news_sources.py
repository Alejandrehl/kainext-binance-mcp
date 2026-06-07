"""Tests de fuentes RSS + cache TTL (plan Task 3, spec §6).

feedparser está MOCKEADO con un feed de ejemplo fijo (no hay red). El cache usa un reloj
inyectable para testear la expiración de forma determinista (sin sleep, sin time.time()).
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from kainext_binance_mcp.models import NewsItem
from kainext_binance_mcp.news import fetch as fetchmod
from kainext_binance_mcp.news import sources as srcmod
from kainext_binance_mcp.news.sources import SOURCES, CoinDeskRSS, CryptoNewsRSS


def _fake_parsed() -> Any:
    """Imita el objeto que devuelve feedparser.parse: .entries (con published_parsed)."""
    return SimpleNamespace(
        bozo=False,
        entries=[
            SimpleNamespace(
                title="Bitcoin surges to new highs",
                summary="A bullish rally pushes BTC up.",
                link="https://example.com/a",
                published_parsed=time.struct_time(
                    (2025, 6, 7, 12, 0, 0, 5, 158, 0)
                ),
            ),
            SimpleNamespace(
                title="Ethereum hacked in exploit",
                summary="ETH plunges after a hack and lawsuit.",
                link="https://example.com/b",
                published_parsed=time.struct_time(
                    (2025, 6, 7, 13, 0, 0, 5, 158, 0)
                ),
            ),
        ],
    )


# --- sources: mapeo entries -> NewsItem ---

def test_coindesk_fetch_maps_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srcmod.feedparser, "parse", lambda url: _fake_parsed())
    items = CoinDeskRSS().fetch()
    assert len(items) == 2
    first = items[0]
    assert isinstance(first, NewsItem)
    assert first.title == "Bitcoin surges to new highs"
    assert first.summary == "A bullish rally pushes BTC up."
    assert first.url == "https://example.com/a"
    assert first.source == "coindesk"
    # published parseado a epoch (UTC) > 0
    assert first.published > 0
    # assets detectados (Task 1) y sentiment (Task 1)
    assert "BTC" in first.assets
    assert first.sentiment > 0
    # el segundo es bearish y menciona ETH
    assert "ETH" in items[1].assets
    assert items[1].sentiment < 0


def test_crypto_news_source_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srcmod.feedparser, "parse", lambda url: _fake_parsed())
    items = CryptoNewsRSS().fetch()
    assert all(i.source == "crypto_news" for i in items)


def test_registry_has_both_sources() -> None:
    assert set(SOURCES.keys()) == {"coindesk", "crypto_news"}


# --- error / vacío: nunca excepción, lista vacía ---

def test_fetch_empty_feed_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        srcmod.feedparser, "parse",
        lambda url: SimpleNamespace(bozo=False, entries=[]),
    )
    assert CoinDeskRSS().fetch() == []


def test_fetch_parse_raises_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str) -> Any:
        raise OSError("network down")

    monkeypatch.setattr(srcmod.feedparser, "parse", boom)
    assert CoinDeskRSS().fetch() == []  # nunca propaga


def test_fetch_entry_without_published(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sin published_parsed → published == 0, sin tumbar el fetch.
    feed = SimpleNamespace(
        bozo=False,
        entries=[
            SimpleNamespace(
                title="BTC news", summary="bitcoin", link="https://e/x",
                published_parsed=None,
            )
        ],
    )
    monkeypatch.setattr(srcmod.feedparser, "parse", lambda url: feed)
    items = CoinDeskRSS().fetch()
    assert len(items) == 1
    assert items[0].published == 0


def test_published_to_epoch_malformed_returns_zero() -> None:
    # struct_time inválido → 0 (no excepción).
    assert srcmod._published_to_epoch("not a struct_time") == 0  # type: ignore[arg-type]


# --- cache TTL con reloj inyectable ---

def test_cache_hits_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def counting_parse(url: str) -> Any:
        calls["n"] += 1
        return _fake_parsed()

    monkeypatch.setattr(srcmod.feedparser, "parse", counting_parse)

    clock = {"t": 1000.0}
    cache = fetchmod.NewsCache(ttl_seconds=300, clock=lambda: clock["t"])
    src = CoinDeskRSS()

    a = cache.fetch(src)
    clock["t"] = 1200.0  # +200s, dentro del TTL de 300
    b = cache.fetch(src)

    assert calls["n"] == 1  # un solo fetch real
    assert [i.url for i in a] == [i.url for i in b]


def test_cache_refetches_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def counting_parse(url: str) -> Any:
        calls["n"] += 1
        return _fake_parsed()

    monkeypatch.setattr(srcmod.feedparser, "parse", counting_parse)

    clock = {"t": 1000.0}
    cache = fetchmod.NewsCache(ttl_seconds=300, clock=lambda: clock["t"])
    src = CoinDeskRSS()

    cache.fetch(src)
    clock["t"] = 1000.0 + 301  # pasado el TTL
    cache.fetch(src)

    assert calls["n"] == 2  # re-fetch


def test_fetch_all_aggregates_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srcmod.feedparser, "parse", lambda url: _fake_parsed())
    cache = fetchmod.NewsCache(ttl_seconds=300, clock=lambda: 1000.0)
    items = fetchmod.fetch_all(list(SOURCES.values()), cache=cache, limit=3)
    assert len(items) == 3  # 2 fuentes x 2 items = 4, limitado a 3


def test_fetch_all_filters_by_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srcmod.feedparser, "parse", lambda url: _fake_parsed())
    cache = fetchmod.NewsCache(ttl_seconds=300, clock=lambda: 1000.0)
    items = fetchmod.fetch_all([CoinDeskRSS()], cache=cache, asset="BTC")
    assert items  # al menos uno
    assert all("BTC" in i.assets for i in items)
