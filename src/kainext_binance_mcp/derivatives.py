"""Capa 5 — derivados públicos de Binance futures (espejo de klines.py).

Endpoints SIN firma (`signed=False` en python-binance): no usan el secret ni requieren
`enableFutures` en la key. La read key viaja como header (inocuo — nota en SECURITY.md).
Con BINANCE_ENV=testnet el client rutea a testnet-fapi → datos sintéticos (disclaimer).
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING

from kainext_binance_mcp.models import DerivativesSnapshot, validate_symbol

if TYPE_CHECKING:
    from binance.client import Client

DISCLAIMER = (
    "Public futures data (funding/OI) is a POSITIONING thermometer, not a prediction. "
    "Interpret with kb://glossary. On testnet this data is synthetic. Not financial advice."
)

FUNDING_HISTORY_LIMIT = 8  # ~últimas 8 ventanas de funding (8h c/u ≈ 2.7 días)


def get_derivatives(client: Client, symbol: str,
                    funding_limit: int = FUNDING_HISTORY_LIMIT) -> DerivativesSnapshot:
    """Snapshot de derivados de un par: mark/index, funding actual + histórico corto, OI.

    Lanza si el par no tiene perp (el error mapeado sale por el contrato de tools)."""
    validate_symbol(symbol)
    if not 1 <= funding_limit <= 100:
        raise ValueError("funding_limit must be between 1 and 100")
    premium = client.futures_mark_price(symbol=symbol)
    history = client.futures_funding_rate(symbol=symbol, limit=funding_limit)
    oi = client.futures_open_interest(symbol=symbol)
    return DerivativesSnapshot(
        symbol=symbol,
        mark_price=Decimal(premium["markPrice"]),
        index_price=Decimal(premium["indexPrice"]),
        last_funding_rate=float(premium["lastFundingRate"]),
        next_funding_time=int(premium["nextFundingTime"]),
        funding_history=[float(h["fundingRate"]) for h in history],
        open_interest=Decimal(oi["openInterest"]),
        as_of=int(time.time() * 1000),
        disclaimer=DISCLAIMER,
    )
