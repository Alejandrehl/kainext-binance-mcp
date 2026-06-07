"""Sentiment léxico determinista + detección de activos (spec §5/N5).

**Honestidad (spec N4):** esto es una señal *cruda*. El léxico es una lista fija de
términos bull/bear con pesos; ``score_text`` cuenta menciones, resta bear de bull y
normaliza a [-1, +1]. NO entiende ironía, contexto ni autoridad de la fuente; no es
predicción. Es puro y sin red (determinista, sin costo, sin API externa).

El léxico es propio y auditable: ver ``_BULL`` / ``_BEAR`` abajo. Cada término lleva un
peso > 0 (la mayoría 1.0; los más fuertes/inequívocos pesan más).
"""
from __future__ import annotations

import re

# --- Léxico bull/bear (auditable). peso > 0; el signo lo da la lista. ---
# Términos de una palabra o multi-palabra; el match es por substring con frontera de
# palabra (\b), case-insensitive. Pesos: 1.0 neutro-fuerte; >1 para señales inequívocas.
_BULL: dict[str, float] = {
    "surge": 1.0,
    "surges": 1.0,
    "rally": 1.0,
    "rallies": 1.0,
    "breakout": 1.0,
    "adoption": 1.0,
    "etf approved": 2.0,
    "bullish": 1.5,
    "gains": 1.0,
    "soar": 1.5,
    "soars": 1.5,
    "pump": 1.0,
    "record high": 1.5,
    "new highs": 1.5,
    "all-time high": 1.5,
    "approved": 1.0,
    "partnership": 1.0,
    "upgrade": 1.0,
    "inflows": 1.0,
}

_BEAR: dict[str, float] = {
    "crash": 1.5,
    "crashes": 1.5,
    "plunge": 1.5,
    "plunges": 1.5,
    "hack": 2.0,
    "hacked": 2.0,
    "exploit": 1.5,
    "ban": 1.0,
    "banned": 1.0,
    "lawsuit": 1.5,
    "sell-off": 1.5,
    "selloff": 1.5,
    "bearish": 1.5,
    "dump": 1.0,
    "scam": 2.0,
    "fraud": 2.0,
    "collapse": 1.5,
    "outflows": 1.0,
    "fears": 1.0,
    "fud": 1.0,
}

# Suma de pesos a la que el score satura a 1.0 (en valor absoluto). Mantiene scores
# realistas sin que un titular muy cargado domine. Determinista.
_SATURATION = 3.0


# --- Tabla de alias de activos (spec N5, ampliable). símbolo -> alias (lower). ---
_ASSET_ALIASES: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth"],
    "SOL": ["solana", "sol"],
    "BNB": ["bnb", "binance coin"],
    "XRP": ["xrp", "ripple"],
    "ADA": ["cardano", "ada"],
    "DOGE": ["dogecoin", "doge"],
}


def _count_weighted(text_lower: str, lexicon: dict[str, float]) -> float:
    """Suma de pesos de los términos del léxico presentes en ``text_lower``.

    Usa frontera de palabra (\\b) para no matchear dentro de otra palabra. Un término
    cuenta su peso por cada aparición.
    """
    total = 0.0
    for term, weight in lexicon.items():
        # re.escape para términos con '-' (sell-off) y espacios (etf approved).
        pattern = r"\b" + re.escape(term) + r"\b"
        hits = len(re.findall(pattern, text_lower))
        total += hits * weight
    return total


def score_text(text: str) -> float:
    """Score de sentiment crudo en [-1, +1]. 0 si no hay términos del léxico.

    score = (Σ pesos bull − Σ pesos bear) / _SATURATION, recortado a [-1, +1].
    Determinista y puro.
    """
    if not text:
        return 0.0
    low = text.lower()
    raw = _count_weighted(low, _BULL) - _count_weighted(low, _BEAR)
    if raw == 0.0:
        return 0.0
    return max(-1.0, min(1.0, raw / _SATURATION))


def detect_assets(text: str) -> list[str]:
    """Activos mencionados en ``text`` por alias (case-insensitive, frontera de palabra).

    Devuelve los símbolos canónicos (BTC, ETH, …) únicos y ordenados. Sin matches → [].
    """
    if not text:
        return []
    low = text.lower()
    found: set[str] = set()
    for symbol, aliases in _ASSET_ALIASES.items():
        for alias in aliases:
            pattern = r"\b" + re.escape(alias) + r"\b"
            if re.search(pattern, low):
                found.add(symbol)
                break
    return sorted(found)
