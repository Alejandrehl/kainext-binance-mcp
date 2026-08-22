"""Idempotencia de órdenes (spec §4.5). El id lo deriva el CONFIRMADOR."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from requests.exceptions import ConnectionError as ReqConnError
from requests.exceptions import Timeout as ReqTimeout

from kainext_binance_mcp.models import CanonicalOrder

# C1: python-binance corre sobre `requests`; un timeout/caída de red real lanza
# requests.exceptions.{Timeout,ConnectionError}, que NO son subclases de los builtins
# TimeoutError/ConnectionError. Si sólo capturáramos los builtins, el query-before-retry
# nunca correría ante un fallo de red real → riesgo de doble orden. Capturamos AMBOS.
_RETRYABLE_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    TimeoutError, ConnectionError, ReqTimeout, ReqConnError,
)


def derive_client_order_id(order: CanonicalOrder, intent_id: str, nonce: str) -> str:
    payload = "|".join([
        order.symbol, order.side, order.type,
        str(order.quantity), str(order.quote_quantity),
        str(order.price), str(order.time_in_force), order.env,
        intent_id, nonce,
    ])
    digest = hashlib.sha256(payload.encode()).hexdigest()[:28]
    return f"kbm_{digest}"  # 4 + 28 = 32 chars, dentro del límite 36 de Binance


def place_order_idempotent(
    *,
    symbol: str,
    client_order_id: str,
    place: Callable[[], dict[str, Any]],
    get_order: Callable[[str, str], dict[str, Any] | None],
) -> dict[str, Any]:
    """Coloca la orden; ante fallo de red NO reintenta a ciegas: consulta por
    origClientOrderId. `get_order` devuelve el dict de la orden o None (-2013)."""
    try:
        return place()
    except _RETRYABLE_NETWORK_ERRORS:
        existing = get_order(symbol, client_order_id)
        if existing is not None:
            return existing  # la orden SÍ se colocó pese al timeout
        return place()  # confirmado que no existe (-2013): seguro reintentar mismo id
