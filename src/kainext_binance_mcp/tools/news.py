"""Tools read-only de capa 3: noticias + sentiment (spec §2/§4).

100% read-only: leen feeds RSS públicos (vía ``news.fetch.fetch_all`` con cache TTL) y
calculan un sentiment **crudo** con el léxico determinista de ``news.sentiment``. NO tocan
el confirmador, NO mueven plata, NO requieren API key.

- ``get_news``: items normalizados, filtrables por activo y por fuentes (valida que las
  fuentes pedidas ⊆ el registro ``SOURCES``).
- ``get_sentiment``: agregado del sentiment de los items que mencionan el activo dentro de
  una ventana temporal. El ``disclaimer`` es obligatorio y explícito: es señal cruda, no
  análisis ni predicción — el juicio fino lo hace Claude leyendo los items del ``sample``.

Los parámetros ``_registry`` / ``_cache`` / ``_now`` son inyectables para testear sin red;
en producción usan los defaults reales (registro ``SOURCES`` + cache de módulo + reloj wall).
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from kainext_binance_mcp.models import NewsItem, SentimentResult
from kainext_binance_mcp.news.fetch import NewsCache, fetch_all
from kainext_binance_mcp.news.sources import SOURCES, NewsSource

# Cache TTL compartido a nivel de módulo (proceso del server): evita martillar las fuentes
# entre llamadas. En tests se inyecta uno fresco vía ``_cache=``.
_MODULE_CACHE = NewsCache()

# Cuántos items representativos adjuntar en SentimentResult.sample (los más recientes).
_SAMPLE_SIZE = 5

# Disclaimer obligatorio (spec §4/N4). Honesto: señal cruda, no análisis ni predicción.
_DISCLAIMER = (
    "Señal CRUDA de sentiment léxico (determinista, sin red): cuenta términos bull/bear "
    "y no entiende ironía, contexto ni la autoridad de la fuente. NO es análisis ni "
    "predicción — usala sólo como indicio y leé los items del sample para juzgar."
)


def _resolve_sources(
    sources: Sequence[str] | None,
    registry: dict[str, NewsSource],
) -> list[NewsSource]:
    """Resuelve los nombres de fuentes pedidos contra el registro.

    Sin ``sources`` → todas las del registro. Si se piden, deben ser ⊆ el registro;
    una fuente desconocida es un error de parámetro (``ValueError``), no una degradación.
    """
    if sources is None:
        return list(registry.values())
    resolved: list[NewsSource] = []
    for name in sources:
        src = registry.get(name)
        if src is None:
            raise ValueError(
                f"fuente desconocida: {name!r}. Disponibles: {sorted(registry)}"
            )
        resolved.append(src)
    return resolved


def get_news(
    asset: str | None = None,
    sources: Sequence[str] | None = None,
    limit: int | None = None,
    *,
    _registry: dict[str, NewsSource] | None = None,
    _cache: NewsCache | None = None,
) -> list[NewsItem]:
    """Noticias crypto normalizadas desde RSS (read-only).

    - ``asset``: si se da, sólo items que mencionan ese símbolo (case-insensitive).
    - ``sources``: subconjunto del registro (``coindesk``, ``crypto_news``); default = todas.
      Una fuente desconocida levanta ``ValueError``.
    - ``limit``: corta tras ordenar por más reciente.
    """
    registry = _registry if _registry is not None else SOURCES
    cache = _cache if _cache is not None else _MODULE_CACHE
    selected = _resolve_sources(sources, registry)
    return fetch_all(selected, cache=cache, asset=asset, limit=limit)


def get_sentiment(
    asset: str,
    window_hours: int = 24,
    *,
    sources: Sequence[str] | None = None,
    _registry: dict[str, NewsSource] | None = None,
    _cache: NewsCache | None = None,
    _now: Callable[[], float] | None = None,
) -> SentimentResult:
    """Sentiment crudo agregado de un activo sobre una ventana temporal (read-only).

    ``score`` = promedio del sentiment de los items que mencionan ``asset`` publicados
    dentro de las últimas ``window_hours`` (0.0 si no hay ninguno). ``sample`` son los
    items más recientes (acotado). ``disclaimer`` siempre poblado (señal cruda).
    """
    registry = _registry if _registry is not None else SOURCES
    cache = _cache if _cache is not None else _MODULE_CACHE
    now = _now if _now is not None else time.time
    selected = _resolve_sources(sources, registry)

    cutoff = now() - window_hours * 3600
    # Items del activo dentro de la ventana, ya ordenados por más reciente (fetch_all ordena).
    items = [
        i
        for i in fetch_all(selected, cache=cache, asset=asset)
        if i.published >= cutoff
    ]

    n_items = len(items)
    score = sum(i.sentiment for i in items) / n_items if n_items else 0.0
    return SentimentResult(
        asset=asset.upper(),
        window_hours=window_hours,
        score=score,
        n_items=n_items,
        sample=items[:_SAMPLE_SIZE],
        disclaimer=_DISCLAIMER,
    )
