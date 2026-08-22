"""Tools de escritura (lado server): proponen y consultan. NUNCA ejecutan (spec §3.2)."""
from __future__ import annotations
from decimal import Decimal
from typing import Any, Protocol
from kainext_binance_mcp.errors import client_secrets, map_binance_error, scrub_secrets
from kainext_binance_mcp.ipc import IpcUnavailableError
from kainext_binance_mcp.models import (
    CanonicalOrder, Env, OrderProposal, OrderPreview, OrderStatus, OrderType,
    Side, TimeInForce, ToolError,
)

_NOT_CANCELABLE = {"FILLED", "CANCELED", "EXPIRED"}


class IpcClient(Protocol):
    def register(self, order: CanonicalOrder) -> tuple[str, int]: ...
    def status(self, intent_id: str) -> dict[str, Any]: ...


def spot_order_propose(*, ipc: IpcClient, market: Any, symbol: str, side: Side, type: OrderType,
                       env: Env, quantity: Decimal | None = None,
                       quote_quantity: Decimal | None = None, price: Decimal | None = None,
                       time_in_force: TimeInForce | None = None) -> OrderProposal:
    if type == "LIMIT" and time_in_force is None:
        time_in_force = "GTC"
    order = CanonicalOrder(symbol=symbol, side=side, type=type, quantity=quantity,
                           quote_quantity=quote_quantity, price=price,
                           time_in_force=time_in_force, env=env)
    estimate: OrderPreview = market.estimate(order)  # pre-validación local (fail-fast, no autoritativa)
    try:
        intent_id, expires_at = ipc.register(order)
    except IpcUnavailableError as e:
        # Mismo contrato que cancel_order_propose: ToolError, nunca una excepción cruda al modelo.
        return OrderProposal(error=ToolError(code="ipc_unavailable", message=str(e)))
    return OrderProposal(intent_id=intent_id, expires_at=expires_at, server_estimate=estimate)


def spot_order_status(*, ipc: IpcClient, intent_id: str) -> OrderStatus:
    return OrderStatus(**ipc.status(intent_id))


def cancel_order_propose(*, ipc: Any, client: Any, symbol: str, order_id: int,
                         env: Env) -> OrderProposal:
    """Re-consulta el estado de la orden ANTES de proponer la cancelación: si ya está
    llenada/cancelada/expirada devuelve un OrderProposal con error (sin crear intent).
    A2: get_order puede lanzar (-2013/red) → se devuelve OrderProposal con error mapeado
    y scrubbeado, nunca un traceback crudo."""
    try:
        current = client.get_order(symbol=symbol, orderId=order_id)
    except Exception as e:  # noqa: BLE001 — sanitizado abajo
        code = getattr(e, "code", -1)
        msg = getattr(e, "message", str(e))
        code = int(code) if isinstance(code, int) else -1
        message = scrub_secrets(map_binance_error(code, str(msg)), client_secrets(client))
        return OrderProposal(error=ToolError(code=code, message=message))
    if current.get("status") in _NOT_CANCELABLE:
        return OrderProposal(error=ToolError(
            code=-2011,
            message=f"Order {order_id} is no longer cancelable (status {current.get('status')}).",
        ))
    try:
        intent_id, expires_at = ipc.register_cancel(symbol=symbol, order_id=order_id, env=env)
    except IpcUnavailableError as e:
        return OrderProposal(error=ToolError(code="ipc_unavailable", message=str(e)))
    return OrderProposal(intent_id=intent_id, expires_at=expires_at)


def cancel_order_status(*, ipc: Any, intent_id: str) -> OrderStatus:
    return OrderStatus(**ipc.status(intent_id))
