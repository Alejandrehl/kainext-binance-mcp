"""Mapeo de errores de Binance a mensajes útiles + scrub de secretos (spec §4.9),
y el contrato de error único de las tools read-only (v1.0.0): toda excepción que salga
de una tool va mapeada + scrubbeada como ToolExecutionError — nunca un traceback crudo."""
from __future__ import annotations

from collections.abc import Callable

_CODE_MESSAGES: dict[int, str] = {
    -2010: "Order rejected: insufficient funds for this order.",
    -1013: "Order rejected by a Binance filter (LOT_SIZE/PRICE_FILTER/NOTIONAL).",
    -1021: "System clock out of sync (timestamp outside recvWindow). Sync NTP / restart.",
    -2011: "Order is no longer cancelable (filled, canceled, or unknown).",
    -1111: "Price or quantity has too many decimals for this symbol.",
    -1100: "Invalid parameter in the order.",
    -2013: "Order does not exist on Binance.",
    -1003: "Too many requests (rate limit). Wait before retrying.",
}


def map_binance_error(code: int, raw_msg: str) -> str:
    base = _CODE_MESSAGES.get(code)
    if base is not None:
        return f"{base} (Binance {code}: {raw_msg})"
    return f"Binance error {code}: {raw_msg}"


def scrub_secrets(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, "***REDACTED***")
    return out


class ToolExecutionError(Exception):
    """Error de tool ya seguro para el modelo: mensaje mapeado + scrubbeado."""


def run_guarded[T](secrets_of: Callable[[], list[str]], fn: Callable[[], T]) -> T:
    """Contrato de error único de las tools read-only. Ejecuta el cuerpo de la tool:
    cualquier excepción (python-binance, red, validación) sale como ToolExecutionError
    con el mensaje mapeado (map_binance_error) y scrubbeado (scrub_secrets). Se llama
    DENTRO del shim (no como decorador): MCPServer introspecciona la firma del shim y un
    wrapper ajeno rompe la resolución de annotations. Las write tools no lo usan: su
    contrato es OrderProposal(error=ToolError) (two-phase, spec §3.2)."""
    try:
        return fn()
    except ToolExecutionError:
        raise
    except ValueError as e:
        # Validación de inputs: el mensaje ya es intencional; sólo scrub.
        raise ToolExecutionError(scrub_secrets(str(e), secrets_of())) from None
    except Exception as e:  # noqa: BLE001 — sanitizado: mapeo + scrub
        code = getattr(e, "code", -1)
        code = code if isinstance(code, int) else -1
        msg = getattr(e, "message", None) or str(e)
        raise ToolExecutionError(
            scrub_secrets(map_binance_error(code, str(msg)), secrets_of())) from None


def client_secrets(client: object) -> list[str]:
    """Key/secret del client para scrubbear mensajes de error (python-binance los guarda
    en client.API_KEY / client.API_SECRET). Sólo strings reales (con un MagicMock en tests
    los atributos no son str y se descartan). Único home (server + confirmador lo comparten)."""
    return [v for v in (getattr(client, "API_KEY", None), getattr(client, "API_SECRET", None))
            if isinstance(v, str) and v]
