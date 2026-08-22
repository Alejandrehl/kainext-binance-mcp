"""Capa 6+ (v1.2) — backtests de las estrategias que la doctrina SÍ recomienda.

No backtesteamos señales (no tienen edge — kb://research/no-edge): backtesteamos
COMPORTAMIENTO — DCA mecánico y grillas de cosecha — sobre históricos reales. Es
simulación histórica, jamás predicción; la sensibilidad a la fecha de inicio es real.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING

from kainext_binance_mcp.klines import fetch_klines_range
from kainext_binance_mcp.models import (
    DcaBacktestResult,
    HarvestBacktestResult,
    HarvestFill,
    validate_symbol,
)

if TYPE_CHECKING:
    from binance.client import Client

_DAY_MS = 86_400_000

DCA_DISCLAIMER = (
    "Historical simulation of a mechanical DCA plan (0.1%/side fee modeled, no slippage) "
    "— NOT a prediction. Results are start-date sensitive: try several windows. "
    "Doctrine: kb://discipline. Not financial advice."
)
HARVEST_DISCLAIMER = (
    "Historical simulation of a pre-committed harvest grid on daily CLOSES (each level "
    "fires once, upward crossing only; fee 0.1% modeled, no slippage) — NOT a prediction. "
    "Doctrine: kb://discipline rule 4. Not financial advice."
)


def backtest_dca(client: Client, symbol: str, monthly_quote: float, months: int,
                 day_of_month: int = 5, fee: float = 0.001) -> DcaBacktestResult:
    """Simula comprar `monthly_quote` (USDT) al CIERRE diario del `day_of_month` de cada
    uno de los últimos `months` meses. Compara contra lump-sum del mismo total el día 1."""
    validate_symbol(symbol)
    if not 1 <= months <= 108:
        raise ValueError("months must be between 1 and 108 (daily history starts 2017)")
    if monthly_quote <= 0:
        raise ValueError("monthly_quote must be > 0")
    if not 1 <= day_of_month <= 28:
        raise ValueError("day_of_month must be between 1 and 28")
    if not 0 <= fee < 0.05:
        raise ValueError("fee must be in [0, 0.05)")

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (months + 1) * 31 * _DAY_MS  # margen para cubrir months compras
    df = fetch_klines_range(client, symbol, "1d", start_ms, now_ms)
    if df.empty:
        raise ValueError(f"no daily history for {symbol} in the requested window")

    import datetime as _dt
    closes = df["close"].astype(float).tolist()
    days = [_dt.datetime.fromtimestamp(t / 1000, _dt.UTC).date() for t in df["open_time"]]

    # una compra por mes calendario: la PRIMERA vela con day >= day_of_month de ese mes
    buys: list[tuple[int, float]] = []  # (índice de vela, precio de compra)
    seen_months: set[tuple[int, int]] = set()
    for i, d in enumerate(days):
        key = (d.year, d.month)
        if key in seen_months or d.day < day_of_month:
            continue
        seen_months.add(key)
        buys.append((i, closes[i]))
    buys = buys[-months:]
    if len(buys) < months:
        raise ValueError(
            f"only {len(buys)} monthly buys available for {symbol} in this window")

    qty = 0.0
    invested = 0.0
    values: list[float] = []  # valor del plan tras cada vela desde la 1ª compra
    first_i = buys[0][0]
    buy_map = dict(buys)
    for i in range(first_i, len(closes)):
        if i in buy_map:
            qty += (monthly_quote * (1 - fee)) / buy_map[i]
            invested += monthly_quote
        values.append(qty * closes[i])

    price_now = closes[-1]
    value_now = qty * price_now
    # lump-sum: todo el total en la primera fecha de compra
    lump_qty = (invested * (1 - fee)) / closes[first_i]
    lump_value = lump_qty * price_now

    peak = values[0] if values else 0.0
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, v / peak - 1)

    return DcaBacktestResult(
        symbol=symbol, months=len(buys), monthly_quote=Decimal(str(monthly_quote)),
        total_invested=Decimal(str(round(invested, 2))),
        accumulated_qty=Decimal(str(round(qty, 8))),
        avg_cost=Decimal(str(round(invested / qty, 2))) if qty > 0 else Decimal("0"),
        value_now=Decimal(str(round(value_now, 2))),
        pnl_pct=round((value_now / invested - 1) * 100, 2) if invested > 0 else 0.0,
        lump_sum_value_now=Decimal(str(round(lump_value, 2))),
        max_drawdown_pct=round(max_dd * 100, 2),
        first_buy_date=str(days[first_i]), last_buy_date=str(days[buys[-1][0]]),
        as_of=now_ms, disclaimer=DCA_DISCLAIMER,
    )


def backtest_harvest(client: Client, symbol: str, initial_qty: float,
                     grid: list[dict[str, float]], start: str | None = None,
                     fee: float = 0.001) -> HarvestBacktestResult:
    """Simula una grilla de cosecha pre-comprometida: cada nivel vende `sell_pct`% del
    holding VIGENTE la primera vez que el cierre diario cruza el nivel al alza."""
    validate_symbol(symbol)
    if initial_qty <= 0:
        raise ValueError("initial_qty must be > 0")
    if not grid:
        raise ValueError("grid must have at least one level")
    levels: list[tuple[float, float]] = []
    for g in grid:
        level, pct = float(g.get("level", 0)), float(g.get("sell_pct", 0))
        if level <= 0 or not 0 < pct <= 100:
            raise ValueError("each grid entry needs level > 0 and 0 < sell_pct <= 100")
        levels.append((level, pct))
    levels.sort()

    import datetime as _dt
    now_ms = int(time.time() * 1000)
    if start is not None:
        start_ms = int(_dt.datetime.fromisoformat(start)
                       .replace(tzinfo=_dt.UTC).timestamp() * 1000)
    else:
        start_ms = now_ms - 365 * _DAY_MS
    df = fetch_klines_range(client, symbol, "1d", start_ms, now_ms)
    if df.empty:
        raise ValueError(f"no daily history for {symbol} in the requested window")
    closes = df["close"].astype(float).tolist()
    days = [str(_dt.datetime.fromtimestamp(t / 1000, _dt.UTC).date())
            for t in df["open_time"]]

    qty = initial_qty
    proceeds = 0.0
    fills: list[HarvestFill] = []
    fired: set[float] = set()
    prev = closes[0]
    for i in range(1, len(closes)):
        c = closes[i]
        for level, pct in levels:
            if level in fired or not (prev < level <= c):
                continue
            sell_qty = qty * pct / 100
            got = sell_qty * level * (1 - fee)  # se asume fill en el nivel (limit order)
            qty -= sell_qty
            proceeds += got
            fired.add(level)
            fills.append(HarvestFill(date=days[i], level=Decimal(str(level)),
                                     qty_sold=Decimal(str(round(sell_qty, 8))),
                                     proceeds=Decimal(str(round(got, 2)))))
        prev = c

    price_now = closes[-1]
    final_value = qty * price_now + proceeds
    hold_value = initial_qty * price_now
    return HarvestBacktestResult(
        symbol=symbol, initial_qty=Decimal(str(initial_qty)), fills=fills,
        remaining_qty=Decimal(str(round(qty, 8))),
        total_proceeds=Decimal(str(round(proceeds, 2))),
        final_value=Decimal(str(round(final_value, 2))),
        pure_hold_value=Decimal(str(round(hold_value, 2))),
        window_start=days[0], window_end=days[-1],
        as_of=now_ms, disclaimer=HARVEST_DISCLAIMER,
    )
