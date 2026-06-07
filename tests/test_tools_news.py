"""Tests de las tools de capa 3: get_news + get_sentiment (plan Task 4, spec §6).

Las fuentes y el fetch están MOCKEADOS (sin red): cada test inyecta un conjunto fijo
de ``NewsItem`` vía ``sources=`` (lista de fuentes fake) o monkeypatcheando ``fetch_all``.
Acá verificamos la lógica de las tools: filtrado por activo, validación de sources,
agregado de sentiment en ventana, disclaimer no vacío. 100% read-only, determinista.
"""
from __future__ import annotations

from typing import Any

import pytest

from kainext_binance_mcp.models import NewsItem, SentimentResult
from kainext_binance_mcp.news.fetch import NewsCache
from kainext_binance_mcp.tools import news as news_tools


class _FakeSource:
    """Fuente fake: nombre estable + lista fija de items (sin red)."""

    def __init__(self, name: str, items: list[NewsItem]) -> None:
        self.name = name
        self._items = items

    def fetch(self) -> list[NewsItem]:
        return list(self._items)


def _item(
    title: str = "Bitcoin surges",
    *,
    assets: list[str] | None = None,
    sentiment: float = 0.5,
    published: int = 1_000_000,
    source: str = "coindesk",
) -> NewsItem:
    return NewsItem(
        title=title,
        summary="",
        source=source,
        published=published,
        url="https://example.com/x",
        assets=assets if assets is not None else ["BTC"],
        sentiment=sentiment,
    )


# Reloj y cache deterministas: TTL irrelevante (cada test arma sus fuentes).
def _cache() -> NewsCache:
    return NewsCache(ttl_seconds=300, clock=lambda: 1000.0)


# --- get_news ---

def test_get_news_returns_items_from_sources() -> None:
    src = _FakeSource("coindesk", [_item("a", assets=["BTC"]), _item("b", assets=["ETH"])])
    out = news_tools.get_news(sources=["coindesk"], _registry={"coindesk": src}, _cache=_cache())
    assert isinstance(out, list)
    assert len(out) == 2
    assert all(isinstance(i, NewsItem) for i in out)


def test_get_news_filters_by_asset() -> None:
    src = _FakeSource(
        "coindesk",
        [_item("a", assets=["BTC"]), _item("b", assets=["ETH"]), _item("c", assets=["BTC", "ETH"])],
    )
    out = news_tools.get_news(asset="BTC", _registry={"coindesk": src}, _cache=_cache())
    assert len(out) == 2
    assert all("BTC" in i.assets for i in out)


def test_get_news_asset_case_insensitive() -> None:
    src = _FakeSource("coindesk", [_item("a", assets=["BTC"])])
    out = news_tools.get_news(asset="btc", _registry={"coindesk": src}, _cache=_cache())
    assert len(out) == 1


def test_get_news_limit_applies() -> None:
    items = [_item(f"t{i}", published=i) for i in range(5)]
    src = _FakeSource("coindesk", items)
    out = news_tools.get_news(limit=2, _registry={"coindesk": src}, _cache=_cache())
    assert len(out) == 2


def test_get_news_default_uses_all_registered_sources() -> None:
    a = _FakeSource("coindesk", [_item("a")])
    b = _FakeSource("crypto_news", [_item("b", source="crypto_news")])
    out = news_tools.get_news(_registry={"coindesk": a, "crypto_news": b}, _cache=_cache())
    assert len(out) == 2


def test_get_news_invalid_source_raises() -> None:
    with pytest.raises(ValueError, match="fuente.*desconocida|nope"):
        news_tools.get_news(
            sources=["nope"], _registry={"coindesk": _FakeSource("coindesk", [])}, _cache=_cache()
        )


def test_get_news_subset_of_registry() -> None:
    a = _FakeSource("coindesk", [_item("a")])
    b = _FakeSource("crypto_news", [_item("b", source="crypto_news")])
    out = news_tools.get_news(
        sources=["crypto_news"], _registry={"coindesk": a, "crypto_news": b}, _cache=_cache()
    )
    assert len(out) == 1
    assert out[0].source == "crypto_news"


# --- get_sentiment ---

def test_get_sentiment_averages_window() -> None:
    now = 2_000_000
    # dentro de ventana (24h = 86400s): dos items BTC con 0.5 y -0.1 → promedio 0.2
    src = _FakeSource(
        "coindesk",
        [
            _item("a", assets=["BTC"], sentiment=0.5, published=now - 100),
            _item("b", assets=["BTC"], sentiment=-0.1, published=now - 200),
            _item("c", assets=["ETH"], sentiment=0.9, published=now - 50),  # otro activo
        ],
    )
    res = news_tools.get_sentiment(
        asset="BTC", _registry={"coindesk": src}, _cache=_cache(), _now=lambda: now
    )
    assert isinstance(res, SentimentResult)
    assert res.asset == "BTC"
    assert res.window_hours == 24
    assert res.n_items == 2
    assert res.score == pytest.approx(0.2)
    assert res.sample  # trae muestra


def test_get_sentiment_window_excludes_old_items() -> None:
    now = 2_000_000
    src = _FakeSource(
        "coindesk",
        [
            _item("recent", assets=["BTC"], sentiment=1.0, published=now - 100),
            _item("old", assets=["BTC"], sentiment=-1.0, published=now - 100_000),  # > 24h
        ],
    )
    res = news_tools.get_sentiment(
        asset="BTC", window_hours=24, _registry={"coindesk": src}, _cache=_cache(), _now=lambda: now
    )
    assert res.n_items == 1
    assert res.score == pytest.approx(1.0)


def test_get_sentiment_disclaimer_not_empty() -> None:
    src = _FakeSource("coindesk", [_item("a", assets=["BTC"], sentiment=0.3)])
    res = news_tools.get_sentiment(
        asset="BTC", _registry={"coindesk": src}, _cache=_cache(), _now=lambda: 2_000_000
    )
    assert res.disclaimer.strip()  # explícita, no vacía
    assert "señal" in res.disclaimer.lower() or "cruda" in res.disclaimer.lower()


def test_get_sentiment_no_items_score_zero() -> None:
    src = _FakeSource("coindesk", [_item("a", assets=["ETH"], sentiment=0.9)])
    res = news_tools.get_sentiment(
        asset="BTC", _registry={"coindesk": src}, _cache=_cache(), _now=lambda: 2_000_000
    )
    assert res.n_items == 0
    assert res.score == 0.0
    assert res.disclaimer.strip()


def test_get_sentiment_custom_window() -> None:
    now = 2_000_000
    src = _FakeSource(
        "coindesk",
        [_item("a", assets=["BTC"], sentiment=0.4, published=now - 3600 * 5)],  # 5h atrás
    )
    # ventana 1h → fuera; ventana 6h → dentro
    out_of = news_tools.get_sentiment(
        asset="BTC", window_hours=1, _registry={"coindesk": src}, _cache=_cache(), _now=lambda: now
    )
    in_win = news_tools.get_sentiment(
        asset="BTC", window_hours=6, _registry={"coindesk": src}, _cache=_cache(), _now=lambda: now
    )
    assert out_of.n_items == 0
    assert in_win.n_items == 1
    assert in_win.window_hours == 6


def test_get_sentiment_sample_capped() -> None:
    now = 2_000_000
    items = [_item(f"t{i}", assets=["BTC"], sentiment=0.1, published=now - i) for i in range(20)]
    src = _FakeSource("coindesk", items)
    res = news_tools.get_sentiment(
        asset="BTC", _registry={"coindesk": src}, _cache=_cache(), _now=lambda: now
    )
    assert res.n_items == 20
    assert len(res.sample) <= 5  # muestra acotada
