"""Ejecución autoritativa en el confirmador (spec §4.3/§4.6). Sólo corre tras el clic."""
from __future__ import annotations
from decimal import Decimal
from typing import Any, Callable
from binance.client import Client
from kainext_binance_mcp.models import CanonicalOrder, OrderResult, ToolError, Fill
from kainext_binance_mcp.idempotency import derive_client_order_id, place_order_idempotent
from kainext_binance_mcp.errors import map_binance_error
from kainext_binance_mcp.intents import IntentStore


def handle_intent(*, order: CanonicalOrder, intent_id: str, store: IntentStore,
                  client: Client, estimator: Any, confirm: Callable[[str], bool], nonce: str) -> None:
    from kainext_binance_mcp_confirmer.dialog import render_dialog_text
    preview = estimator.estimate(order)          # AUTORITATIVO: el confirmador re-valida
    if not preview.feasible:
        store.mark_failed(intent_id, ToolError(code="infeasible", message=preview.reason or "no ejecutable"))
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
        store.mark_executed(intent_id, _to_result(raw, order.env))
    except Exception as e:  # noqa: BLE001 — sanitizado abajo
        code, msg = _extract(e)
        store.mark_failed(intent_id, ToolError(code=code, message=map_binance_error(code, msg)))


def _create(client: Client, order: CanonicalOrder, preview: Any, cid: str) -> dict[str, Any]:
    params: dict[str, Any] = {"symbol": order.symbol, "side": order.side,
                              "type": order.type, "newClientOrderId": cid}
    if order.type == "LIMIT":
        params.update(timeInForce=order.time_in_force, price=str(preview.price),
                      quantity=str(preview.effective_qty))
    elif order.quote_quantity is not None:
        params.update(quoteOrderQty=str(order.quote_quantity))
    else:
        params.update(quantity=str(preview.effective_qty))
    return client.create_order(**params)


def _get_order(client: Client, symbol: str, cid: str) -> dict[str, Any] | None:
    try:
        return client.get_order(symbol=symbol, origClientOrderId=cid)
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


def _extract(e: Exception) -> tuple[int, str]:
    code = getattr(e, "code", -1)
    msg = getattr(e, "message", str(e))
    return int(code) if isinstance(code, int) else -1, str(msg)
