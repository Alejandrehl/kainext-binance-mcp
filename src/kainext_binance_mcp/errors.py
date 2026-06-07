"""Mapeo de errores de Binance a mensajes útiles + scrub de secretos (spec §4.9)."""
from __future__ import annotations

_CODE_MESSAGES: dict[int, str] = {
    -2010: "Orden rechazada: fondos insuficientes para esta orden.",
    -1013: "Orden rechazada por un filtro de Binance (LOT_SIZE/PRICE_FILTER/NOTIONAL).",
    -1021: "Reloj del sistema desincronizado (timestamp fuera de recvWindow). Sincronizá NTP/reiniciá.",
    -2011: "La orden ya no es cancelable (llenada, cancelada o inexistente).",
    -1111: "Precio o cantidad con demasiados decimales para el símbolo.",
    -1100: "Parámetro inválido en la orden.",
    -2013: "La orden no existe en Binance.",
    -1003: "Demasiadas requests (rate limit). Esperá antes de reintentar.",
}


class BinanceMcpError(Exception):
    """Error de dominio con código y mensaje ya sanitizado."""

    def __init__(self, code: int | str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def map_binance_error(code: int, raw_msg: str) -> str:
    base = _CODE_MESSAGES.get(code)
    if base is not None:
        return f"{base} (Binance {code}: {raw_msg})"
    return f"Error de Binance {code}: {raw_msg}"


def scrub_secrets(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, "***REDACTED***")
    return out
