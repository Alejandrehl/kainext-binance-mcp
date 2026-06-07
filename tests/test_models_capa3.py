"""Tests de construcción de los modelos de capa 3 (plan Task 2, spec §4)."""
from __future__ import annotations

from kainext_binance_mcp.models import NewsItem, SentimentResult


def test_news_item_construct() -> None:
    item = NewsItem(
        title="Bitcoin surges to new highs",
        summary="A bullish rally pushes BTC up.",
        source="coindesk",
        published=1717000000,
        url="https://example.com/a",
        assets=["BTC"],
        sentiment=0.5,
    )
    assert item.title == "Bitcoin surges to new highs"
    assert item.source == "coindesk"
    assert item.published == 1717000000
    assert item.assets == ["BTC"]
    assert item.sentiment == 0.5


def test_news_item_defaults() -> None:
    item = NewsItem(
        title="t",
        summary="s",
        source="crypto_news",
        published=0,
        url="https://x",
    )
    assert item.assets == []
    assert item.sentiment == 0.0


def test_sentiment_result_construct() -> None:
    item = NewsItem(
        title="t",
        summary="s",
        source="coindesk",
        published=1,
        url="https://x",
        assets=["ETH"],
        sentiment=-0.3,
    )
    res = SentimentResult(
        asset="ETH",
        window_hours=24,
        score=-0.3,
        n_items=1,
        sample=[item],
        disclaimer="señal cruda, no es análisis",
    )
    assert res.asset == "ETH"
    assert res.window_hours == 24
    assert res.n_items == 1
    assert res.sample[0] is item
    assert res.disclaimer
