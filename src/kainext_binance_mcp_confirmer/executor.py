"""Ejecución autoritativa en el confirmador (spec §4.3/§4.6). Sólo corre tras el clic."""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

from binance.client import Client

from kainext_binance_mcp.errors import client_secrets, map_binance_error, scrub_secrets
from kainext_binance_mcp.idempotency import derive_client_order_id, place_order_idempotent
from kainext_binance_mcp.intents import IntentStore
from kainext_binance_mcp.models import (
    NOT_CANCELABLE,
    CancelResult,
    CanonicalOrder,
    Fill,
    OrderResult,
    ToolError,
)


def _fail(store: IntentStore, intent_id: str, client: Client, e: Exception) -> None:
    """C2: construye el ToolError de un fallo SANITIZADO. El mensaje pasa por scrub_secrets
    con la key/secret del client → la API key/secret nunca se filtra al modelo."""
    code, msg = _extract(e)
    message = scrub_secrets(map_binance_error(code, msg), client_secrets(client))
    store.mark_failed(intent_id, ToolError(code=code, message=message))


def handle_intent(*, order: CanonicalOrder, intent_id: str, store: IntentStore,
                  client: Client, estimator: Any, confirm: Callable[[str], bool], nonce: str,
                  confirmer_env: str = "testnet", audit_path: str | None = None) -> None:
    from kainext_binance_mcp_confirmer.dialog import render_dialog_text
    # C3: el env del intent lo controla el MODELO (viene del wire). La ejecución ocurre
    # contra el client del confirmador (atado a SU BINANCE_ENV). Si difieren, el humano
    # vería un banner (p.ej. TESTNET) y se ejecutaría en otro entorno (p.ej. mainnet).
    # Validamos ANTES de estimar/mostrar diálogo: si no coinciden → mark_failed, sin diálogo.
    if order.env != confirmer_env:
        store.mark_failed(intent_id, ToolError(
            code="env_mismatch",
            message=(f"intent env ({order.env}) does not match the confirmer env "
                     f"({confirmer_env}); no dialog shown, nothing executed")))
        return
    try:
        preview = estimator.estimate(order)      # AUTORITATIVO: el confirmador re-valida
    except Exception as e:  # noqa: BLE001 — si la estimación falla (red/símbolo), el intent
        _fail(store, intent_id, client, e)       # debe quedar failed, no pending hasta el TTL
        return
    if not preview.feasible:
        store.mark_failed(intent_id, ToolError(
            code="infeasible", message=preview.reason or "not executable"))
        return
    if not confirm(render_dialog_text(order, preview)):
        store.mark_rejected(intent_id)
        return
    store.mark_approved(intent_id)
    cid = derive_client_order_id(order, intent_id, nonce)
    try:
        raw = place_order_idempotent(
            symbol=order.symbol, client_order_id=cid,
            place=lambda: _create(client, order, preview, cid),
            get_order=lambda s, c: _get_order(client, s, c),
        )
        result = _to_result(raw, order.env)
        store.mark_executed(intent_id, result)
        if audit_path is not None:  # A1: registro de auditoría tras ejecutar (sin secretos)
            _audit_order(audit_path, intent_id, order, result, preview)
    except Exception as e:  # noqa: BLE001 — sanitizado en _fail (scrub de secretos)
        _fail(store, intent_id, client, e)


def handle_cancel_intent(*, symbol: str, order_id: int, env: str, intent_id: str,
                         store: IntentStore, client: Client,
                         confirm: Callable[[str], bool],
                         confirmer_env: str = "testnet",
                         audit_path: str | None = None) -> None:
    """Cancelación autoritativa. Re-consulta estado JUSTO antes de cancelar (TOCTOU,
    spec §4.3/§3.2) y NUNCA cancela sin el clic. Invariante: sin confirm → no cancela."""
    from kainext_binance_mcp_confirmer.dialog import render_cancel_dialog_text
    # C3: igual que en handle_intent, el env del intent lo controla el modelo; validar
    # contra el env del confirmador ANTES de consultar/mostrar diálogo/cancelar.
    if env != confirmer_env:
        store.mark_failed(intent_id, ToolError(
            code="env_mismatch",
            message=(f"intent env ({env}) does not match the confirmer env "
                     f"({confirmer_env}); no dialog shown, nothing canceled")))
        return
    try:
        current = client.get_order(symbol=symbol, orderId=order_id)
    except Exception as e:  # noqa: BLE001
        _fail(store, intent_id, client, e)
        return
    status = current.get("status")
    if status in NOT_CANCELABLE:
        store.mark_failed(intent_id, ToolError(
            code=-2011, message=f"La orden {order_id} ya no es cancelable (estado {status})."))
        return
    if not confirm(render_cancel_dialog_text(symbol=symbol, order_id=order_id, env=env,
                                              status=status)):
        store.mark_rejected(intent_id)
        return
    store.mark_approved(intent_id)
    try:
        raw = client.cancel_order(symbol=symbol, orderId=order_id)
        result = _to_cancel_result(raw, env)
        store.mark_executed(intent_id, result)
        if audit_path is not None:  # A1: registro de auditoría tras cancelar (sin secretos)
            _audit_cancel(audit_path, intent_id, symbol, result)
    except Exception as e:  # noqa: BLE001
        _fail(store, intent_id, client, e)




def _to_cancel_result(raw: dict[str, Any], env: str) -> CancelResult:
    """B3: la cancelación produce un CancelResult (spec §3.3), no un OrderResult. El path de
    cancelación sólo llega acá tras una cancel_order exitosa → status CANCELED."""
    status = raw.get("status", "CANCELED")
    return CancelResult(
        order_id=raw["orderId"],
        status="CANCELED" if status == "CANCELED" else "NOT_CANCELABLE",
        detail=f"orden {raw['orderId']} {status}",
        env=env)  # type: ignore[arg-type]


def _create(client: Client, order: CanonicalOrder, preview: Any, cid: str) -> dict[str, Any]:
    # B2 (nota de divergencia estimate vs execute): el ESTIMATE deriva una effective_qty a
    # partir del quote (precio × cantidad) sólo para previsualizar el notional; la EJECUCIÓN
    # de un MARKET-by-quote manda el quoteOrderQty CRUDO que pidió el usuario (no la qty
    # derivada). Es intencional: Binance valida el NOTIONAL real al ejecutar (filtro NOTIONAL),
    # así que no re-derivamos cantidad acá — dejamos que el exchange sea la autoridad del notional.
    params: dict[str, Any] = {"symbol": order.symbol, "side": order.side,
                              "type": order.type, "newClientOrderId": cid}
    if order.type == "LIMIT":
        params.update(timeInForce=order.time_in_force, price=str(preview.price),
                      quantity=str(preview.effective_qty))
    elif order.quote_quantity is not None:
        params.update(quoteOrderQty=str(order.quote_quantity))
    else:
        params.update(quantity=str(preview.effective_qty))
    return cast("dict[str, Any]", client.create_order(**params))


def _get_order(client: Client, symbol: str, cid: str) -> dict[str, Any] | None:
    try:
        return cast("dict[str, Any]", client.get_order(symbol=symbol, origClientOrderId=cid))
    except Exception:  # noqa: BLE001
        return None


def _to_result(raw: dict[str, Any], env: str) -> OrderResult:
    fills = [Fill(price=Decimal(x["price"]), qty=Decimal(x["qty"]),
                  commission=Decimal(x["commission"]), commission_asset=x["commissionAsset"])
             for x in raw.get("fills", [])]
    return OrderResult(order_id=raw["orderId"], client_order_id=raw["clientOrderId"],
                       status=raw["status"], executed_qty=Decimal(raw["executedQty"]),
                       cummulative_quote_qty=Decimal(raw.get("cummulativeQuoteQty", "0")),
                       fills=fills, env=env)  # type: ignore[arg-type]


def _audit_order(audit_path: str, intent_id: str, order: CanonicalOrder,
                 result: OrderResult, preview: Any) -> None:
    """A1: appendea la orden ejecutada al audit log (best-effort; nunca tumba la ejecución
    ni filtra secretos). `effective_qty` = cantidad ORDENADA (lo que se colocó, redondeado);
    `executed_qty` = lo llenado hasta ahora (0 si la LIMIT quedó resting);
    `price` = el de la orden."""
    from kainext_binance_mcp_confirmer.audit import append_audit_entry

    # El audit es best-effort: NUNCA debe romper el flujo de ejecución.
    with contextlib.suppress(Exception):
        append_audit_entry(
            path=audit_path, intent_id=intent_id, action="ORDER",
            client_order_id=result.client_order_id, order_id=result.order_id,
            symbol=order.symbol, side=order.side,
            effective_qty=preview.effective_qty, executed_qty=result.executed_qty,
            price=order.price, env=result.env)


def _audit_cancel(audit_path: str, intent_id: str, symbol: str,
                  result: CancelResult) -> None:
    """A1: appendea la cancelación ejecutada al audit log (best-effort; nunca tumba el flujo
    ni filtra secretos). Una cancelación no tiene side/qty/price → van None; action='CANCEL'."""
    from kainext_binance_mcp_confirmer.audit import append_audit_entry

    # El audit es best-effort: NUNCA debe romper el flujo de ejecución.
    with contextlib.suppress(Exception):
        append_audit_entry(
            path=audit_path, intent_id=intent_id, action="CANCEL",
            client_order_id="", order_id=result.order_id,
            symbol=symbol, side="", effective_qty=None, price=None, env=result.env)


def _extract(e: Exception) -> tuple[int, str]:
    code = getattr(e, "code", -1)
    msg = getattr(e, "message", str(e))
    return int(code) if isinstance(code, int) else -1, str(msg)
