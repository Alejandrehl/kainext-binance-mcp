"""Diálogo nativo macOS. El TEXTO se renderiza desde el CanonicalOrder que se ejecuta
(spec §4.3): el humano ve exactamente lo que se ejecuta. NUNCA texto provisto por el server."""
from __future__ import annotations

import subprocess

from kainext_binance_mcp.models import CanonicalOrder, OrderPreview
from kainext_binance_mcp_confirmer.confirm_backends import (
    CONFIRM_TIMEOUT_S as _DIALOG_TIMEOUT_S,  # noqa: E501 — timeout único de confirmación (v1.2)
)


def render_dialog_text(order: CanonicalOrder, preview: OrderPreview) -> str:
    env_banner = "⚠️ REAL MONEY (MAINNET)" if order.env == "mainnet" else "TESTNET"
    lines = [
        env_banner, "",
        f"{order.side} {order.type}  {order.symbol}",
        f"Effective quantity: {preview.effective_qty}",
    ]
    if order.price is not None:
        lines.append(f"Price: {preview.price}  ({order.time_in_force})")
    if order.type == "MARKET":
        lines.append(
            "(MARKET: quantity/cost are estimates; you approve the QUANTITY, not the cost)")
    lines.append(f"Estimated notional: {preview.est_notional}")
    return "\n".join(lines)


def render_cancel_dialog_text(*, symbol: str, order_id: int, env: str,
                              status: str | None = None) -> str:
    """Texto del diálogo de cancelación. Como el resto del gate, lo renderiza el
    confirmador desde los campos que él mismo va a ejecutar (spec §4.3)."""
    env_banner = "⚠️ REAL MONEY (MAINNET)" if env == "mainnet" else "TESTNET"
    lines = [env_banner, "", f"CANCEL order {order_id}  {symbol}"]
    if status is not None:
        lines.append(f"Current status: {status}")
    return "\n".join(lines)


def parse_osascript_result(*, returncode: int, stdout: str) -> bool:
    # Confirm = exit 0, no timeout, and 'button returned:Confirm' present.
    # OJO: con `giving up after`, osascript anexa ", gave up:false" al stdout
    # (e.g. "button returned:Confirm, gave up:false") → do NOT use endswith.
    # Cancelar/Esc => exit != 0 ("User canceled. (-128)"); timeout => "gave up:true".
    if returncode != 0 or "gave up:true" in stdout:
        return False
    return "button returned:Confirm" in stdout


def escape_applescript(text: str) -> str:
    """Escape para literal de string AppleScript: backslash PRIMERO, luego comillas.
    Único punto donde texto derivado del CanonicalOrder entra a un intérprete."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def ask_confirmation(text: str) -> bool:
    safe = escape_applescript(text)
    script = (
        f'display dialog "{safe}" buttons {{"Cancel","Confirm"}} '
        f'default button "Cancel" cancel button "Cancel" '
        f'with title "Binance MCP — confirm order" with icon caution '
        f'giving up after {_DIALOG_TIMEOUT_S}'
    )
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return parse_osascript_result(returncode=proc.returncode, stdout=proc.stdout)
