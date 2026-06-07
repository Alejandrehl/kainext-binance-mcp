"""Tools de escritura (lado server): proponen y consultan. NUNCA ejecutan (spec §3.2)."""
from __future__ import annotations
from decimal import Decimal
from typing import Any, Protocol
from kainext_binance_mcp.models import (
    CanonicalOrder, OrderProposal, OrderStatus, OrderPreview, ToolError,
)

_NOT_CANCELABLE = {"FILLED", "CANCELED", "EXPIRED"}


class IpcClient(Protocol):
    def register(self, order: CanonicalOrder) -> tuple[str, int]: ...
    def status(self, intent_id: str) -> dict[str, Any]: ...


def spot_order_propose(*, ipc: IpcClient, market: Any, symbol: str, side: str, type: str,
                       env: str, quantity: Decimal | None = None,
                       quote_quantity: Decimal | None = None, price: Decimal | None = None,
                       time_in_force: str | None = None) -> OrderProposal:
    if type == "LIMIT" and time_in_force is None:
        time_in_force = "GTC"
    order = CanonicalOrder(symbol=symbol, side=side, type=type, quantity=quantity,
                           quote_quantity=quote_quantity, price=price,
                           time_in_force=time_in_force, env=env)
    estimate: OrderPreview = market.estimate(order)  # pre-validación local (fail-fast, no autoritativa)
    intent_id, expires_at = ipc.register(order)
    return OrderProposal(intent_id=intent_id, expires_at=expires_at, server_estimate=estimate)


def spot_order_status(*, ipc: IpcClient, intent_id: str) -> OrderStatus:
    return OrderStatus(**ipc.status(intent_id))


def cancel_order_propose(*, ipc: Any, client: Any, symbol: str, order_id: int,
                         env: str) -> OrderProposal:
    """Re-consulta el estado de la orden ANTES de proponer la cancelación: si ya está
    llenada/cancelada/expirada devuelve un OrderProposal con error (sin crear intent)."""
    current = client.get_order(symbol=symbol, orderId=order_id)
    if current.get("status") in _NOT_CANCELABLE:
        return OrderProposal(error=ToolError(
            code=-2011,
            message=f"La orden {order_id} ya no es cancelable (estado {current.get('status')}).",
        ))
    intent_id, expires_at = ipc.register_cancel(symbol=symbol, order_id=order_id, env=env)
    return OrderProposal(intent_id=intent_id, expires_at=expires_at)


def cancel_order_status(*, ipc: Any, intent_id: str) -> OrderStatus:
    return OrderStatus(**ipc.status(intent_id))
