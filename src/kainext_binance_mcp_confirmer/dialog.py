"""Diálogo nativo macOS. El TEXTO se renderiza desde el CanonicalOrder que se ejecuta
(spec §4.3): el humano ve exactamente lo que se ejecuta. NUNCA texto provisto por el server."""
from __future__ import annotations
import subprocess
from kainext_binance_mcp.models import CanonicalOrder, OrderPreview

_DIALOG_TIMEOUT_S = 45  # < tool-call timeout del cliente (spec §2.1.9); para MARKET ver §4.8


def render_dialog_text(order: CanonicalOrder, preview: OrderPreview) -> str:
    env_banner = "⚠️ PLATA REAL (MAINNET)" if order.env == "mainnet" else "TESTNET"
    lines = [
        env_banner, "",
        f"{order.side} {order.type}  {order.symbol}",
        f"Cantidad efectiva: {preview.effective_qty}",
    ]
    if order.price is not None:
        lines.append(f"Precio: {preview.price}  ({order.time_in_force})")
    if order.type == "MARKET":
        lines.append("(MARKET: cantidad/costo estimados; aprobás la CANTIDAD, no el costo)")
    lines.append(f"Notional estimado: {preview.est_notional}")
    return "\n".join(lines)


def render_cancel_dialog_text(*, symbol: str, order_id: int, env: str,
                              status: str | None = None) -> str:
    """Texto del diálogo de cancelación. Como el resto del gate, lo renderiza el
    confirmador desde los campos que él mismo va a ejecutar (spec §4.3)."""
    env_banner = "⚠️ PLATA REAL (MAINNET)" if env == "mainnet" else "TESTNET"
    lines = [env_banner, "", f"CANCELAR orden {order_id}  {symbol}"]
    if status is not None:
        lines.append(f"Estado actual: {status}")
    return "\n".join(lines)


def parse_osascript_result(*, returncode: int, stdout: str) -> bool:
    # Confirmar = exit 0 + 'button returned:Confirmar'. Cualquier otra cosa = NO ejecutar.
    return returncode == 0 and stdout.strip().endswith(":Confirmar")


def ask_confirmation(text: str) -> bool:
    safe = text.replace('"', "'")
    script = (
        f'display dialog "{safe}" buttons {{"Cancelar","Confirmar"}} '
        f'default button "Cancelar" cancel button "Cancelar" '
        f'with title "Binance MCP — confirmar orden" with icon caution '
        f'giving up after {_DIALOG_TIMEOUT_S}'
    )
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if "gave up:true" in proc.stdout:
        return False
    return parse_osascript_result(returncode=proc.returncode, stdout=proc.stdout)
