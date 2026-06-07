"""Fuentes de noticias RSS pluggable (spec §3, N2/N2.1).

Cada fuente es un ``NewsSource``: un ``name`` y un ``fetch()`` que devuelve ``list[NewsItem]``.
Hoy: CoinDesk y crypto.news (RSS sin API key). X/Twitter queda DIFERIDO (spec N2): se
agregaría como un adaptador nuevo + su key por env, sin tocar el resto.

**Robustez (spec N3/N6):** ``fetch()`` nunca propaga una excepción ni tumba la tool —
feed vacío, error de red o feed malformado → ``[]`` (se loggea). Es 100% read-only.
"""
from __future__ import annotations

import calendar
import logging
import socket
from time import struct_time
from typing import Protocol, runtime_checkable

import feedparser

from kainext_binance_mcp.models import NewsItem
from kainext_binance_mcp.news.sentiment import detect_assets, score_text

logger = logging.getLogger(__name__)

# Timeout corto para no colgar la tool si una fuente responde lento (spec N3).
FETCH_TIMEOUT_SECONDS = 8.0


@runtime_checkable
class NewsSource(Protocol):
    """Adaptador de fuente: un nombre estable + un fetch read-only."""

    name: str

    def fetch(self) -> list[NewsItem]: ...


def _published_to_epoch(parsed: struct_time | None) -> int:
    """``published_parsed`` (struct_time UTC de feedparser) → epoch en segundos.

    feedparser entrega la fecha ya normalizada a UTC; ``calendar.timegm`` la interpreta
    como UTC (no usar ``time.mktime``, que asume local). Sin fecha → 0.
    """
    if parsed is None:
        return 0
    try:
        return int(calendar.timegm(parsed))
    except (OverflowError, ValueError, TypeError):
        return 0


class _RSSSource:
    """Base de las fuentes RSS: parsea ``url`` con feedparser y mapea entries→NewsItem."""

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url

    def fetch(self) -> list[NewsItem]:
        # feedparser no expone timeout propio; usa urllib (socket). Acotamos con el
        # timeout de socket por defecto durante la llamada y lo restauramos siempre.
        prev_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(FETCH_TIMEOUT_SECONDS)
            parsed = feedparser.parse(self.url)
        except Exception as exc:  # noqa: BLE001 — read-only: degradar a [] sin tumbar la tool
            logger.warning("news source %s failed to parse: %s", self.name, exc)
            return []
        finally:
            socket.setdefaulttimeout(prev_timeout)

        entries = getattr(parsed, "entries", []) or []
        items: list[NewsItem] = []
        for e in entries:
            title = getattr(e, "title", "") or ""
            summary = getattr(e, "summary", "") or ""
            url = getattr(e, "link", "") or ""
            published = _published_to_epoch(getattr(e, "published_parsed", None))
            text = f"{title}. {summary}"
            items.append(
                NewsItem(
                    title=title,
                    summary=summary,
                    source=self.name,
                    published=published,
                    url=url,
                    assets=detect_assets(text),
                    sentiment=score_text(text),
                )
            )
        return items


class CoinDeskRSS(_RSSSource):
    """CoinDesk RSS (spec N2)."""

    def __init__(self) -> None:
        super().__init__("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/")


class CryptoNewsRSS(_RSSSource):
    """crypto.news RSS (spec N2)."""

    def __init__(self) -> None:
        super().__init__("crypto_news", "https://crypto.news/feed/")


# Registro de fuentes activas (spec N2.1). Agregar una fuente = una entrada aquí.
SOURCES: dict[str, NewsSource] = {
    "coindesk": CoinDeskRSS(),
    "crypto_news": CryptoNewsRSS(),
}
