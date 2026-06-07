"""Filtros de símbolo y redondeo Decimal a tick/step (spec §2.1.3/§4.6)."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any


@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    market_step_size: Decimal
    min_notional: Decimal


def round_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step == 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def round_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    if tick == 0:
        return price
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def validate_notional(qty: Decimal, price: Decimal, min_notional: Decimal) -> str | None:
    if qty * price < min_notional:
        return f"notional {qty * price} < mínimo {min_notional}"
    return None


def parse_symbol_filters(info: dict[str, Any]) -> SymbolFilters:
    """Construye SymbolFilters desde el dict de client.get_symbol_info()."""
    f = {x["filterType"]: x for x in info["filters"]}
    lot = f.get("LOT_SIZE", {})
    mlot = f.get("MARKET_LOT_SIZE", lot)
    notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
    return SymbolFilters(
        symbol=info["symbol"],
        tick_size=Decimal(f["PRICE_FILTER"]["tickSize"]),
        step_size=Decimal(lot["stepSize"]),
        market_step_size=Decimal(mlot.get("stepSize", lot["stepSize"])),
        min_notional=Decimal(notional.get("minNotional", "0")),
    )
