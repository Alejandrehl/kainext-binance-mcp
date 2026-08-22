"""Filtros de símbolo y redondeo Decimal a tick/step (spec §2.1.3/§4.6)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from kainext_binance_mcp.models import CanonicalOrder, OrderPreview


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


class MarketEstimator:
    """Pre-validación/estimación. La usa el server (no autoritativa) Y el confirmador
    (autoritativa). Misma lógica para que no diverjan."""

    def __init__(self, get_filters: Callable[[str], SymbolFilters],
                 get_price: Callable[[str], Decimal]) -> None:
        self._get_filters = get_filters
        self._get_price = get_price

    def estimate(self, order: CanonicalOrder) -> OrderPreview:
        f = self._get_filters(order.symbol)
        warnings: list[str] = []
        ref_price = order.price if order.price is not None else self._get_price(order.symbol)
        if order.type == "MARKET":
            warnings.append("MARKET: cantidad/costo estimados, sujetos a slippage")
        if order.quote_quantity is not None:
            eff_qty = round_to_step(order.quote_quantity / ref_price, f.market_step_size)
        else:
            step = f.step_size if order.type == "LIMIT" else f.market_step_size
            eff_qty = round_to_step(order.quantity, step)  # type: ignore[arg-type]
        eff_price = round_to_tick(ref_price, f.tick_size) if order.price is not None else ref_price
        reason = validate_notional(eff_qty, eff_price, f.min_notional)
        notional = eff_qty * eff_price
        return OrderPreview(
            effective_qty=eff_qty, price=eff_price if order.price is not None else None,
            est_notional=notional, est_commission=notional * Decimal("0.001"),
            env=order.env, warnings=warnings, feasible=reason is None, reason=reason,
        )
