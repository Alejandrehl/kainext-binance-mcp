"""Fetch de noticias con cache TTL en memoria (spec §3, N3).

El cache evita martillar las fuentes: dentro del TTL, ``fetch`` devuelve lo cacheado;
pasado el TTL, re-fetch. El reloj es **inyectable** (``clock``) para testear la
expiración de forma determinista (sin ``sleep`` ni ``time.time()`` hardcodeado).

100% read-only. Errores de fuente ya degradan a ``[]`` dentro de cada ``NewsSource.fetch``.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from kainext_binance_mcp.models import NewsItem
from kainext_binance_mcp.news.sources import NewsSource

DEFAULT_TTL_SECONDS = 300  # 5 min (spec N3)


class NewsCache:
    """Cache TTL por fuente (clave = ``source.name``), con reloj inyectable.

    ``clock`` devuelve "ahora" en segundos (default ``time.monotonic``). Cada entrada
    guarda ``(timestamp, items)``; se considera fresca si ``now - timestamp < ttl``.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, list[NewsItem]]] = {}

    def fetch(self, source: NewsSource) -> list[NewsItem]:
        """Items de ``source``, usando cache si la entrada sigue fresca dentro del TTL."""
        now = self._clock()
        cached = self._entries.get(source.name)
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]
        items = source.fetch()
        self._entries[source.name] = (now, items)
        return items


def fetch_all(
    sources: Sequence[NewsSource],
    cache: NewsCache | None = None,
    asset: str | None = None,
    limit: int | None = None,
) -> list[NewsItem]:
    """Agrega items de varias ``sources`` (vía cache), filtra por activo y aplica ``limit``.

    - ``asset``: si se da, sólo items que mencionan ese símbolo (case-insensitive).
    - Orden: más recientes primero (``published`` desc).
    - ``limit``: corta tras ordenar.
    """
    cache = cache or NewsCache()
    items: list[NewsItem] = []
    for source in sources:
        items.extend(cache.fetch(source))

    if asset is not None:
        target = asset.upper()
        items = [i for i in items if target in i.assets]

    items.sort(key=lambda i: i.published, reverse=True)

    if limit is not None:
        items = items[:limit]
    return items
