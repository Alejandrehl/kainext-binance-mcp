"""Backtesters de la doctrina (v1.2): DCA + grilla, con klines sintéticas a mano."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kainext_binance_mcp.klines import fetch_klines_range
from kainext_binance_mcp.plans import backtest_dca, backtest_harvest

_DAY_MS = 86_400_000


def _daily_raw(start: dt.date, closes: list[float]) -> list[list[object]]:
    base = int(dt.datetime(start.year, start.month, start.day,
                           tzinfo=dt.UTC).timestamp() * 1000)
    out = []
    for i, c in enumerate(closes):
        t = base + i * _DAY_MS
        out.append([t, str(c), str(c), str(c), str(c), "1", t + _DAY_MS - 1,
                    "1", 1, "1", "1", "0"])
    return out


def _client_with(closes: list[float], start: dt.date) -> MagicMock:
    c = MagicMock()
    c.get_klines.return_value = _daily_raw(start, closes)
    return c


# --- fetch_klines_range: paginación ---

def test_fetch_klines_range_paginates() -> None:
    c = MagicMock()
    start = dt.date(2024, 1, 1)
    page1 = _daily_raw(start, [100.0] * 1000)
    page2 = _daily_raw(start + dt.timedelta(days=1000), [100.0] * 10)
    c.get_klines.side_effect = [page1, page2]
    end_ms = int(page2[-1][6]) + 1
    df = fetch_klines_range(c, "BTCUSDT", "1d", int(page1[0][0]), end_ms)
    assert len(df) == 1010 and c.get_klines.call_count == 2
    # el segundo call parte después del close de la primera página
    assert c.get_klines.call_args_list[1].kwargs["startTime"] == int(page1[-1][6]) + 1


def test_fetch_klines_range_validates() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="interval"):
        fetch_klines_range(c, "BTCUSDT", "5x", 0, 1)
    with pytest.raises(ValueError, match="start_ms"):
        fetch_klines_range(c, "BTCUSDT", "1d", 5, 5)


# --- DCA (verificado a mano) ---

def test_backtest_dca_two_months_hand_computed() -> None:
    # 70 días desde el 01-jun: compras el día 5 de jun (close 100) y 5 de jul (close 200).
    closes = [100.0] * 40 + [200.0] * 30
    client = _client_with(closes, dt.date(2024, 6, 1))
    res = backtest_dca(client, "BTCUSDT", monthly_quote=1000, months=2,
                       day_of_month=5, fee=0.0)
    # compra 1: 1000/100 = 10 unidades · compra 2: 1000/200 = 5 unidades
    assert res.accumulated_qty == Decimal("15")
    assert res.total_invested == Decimal("2000")
    assert res.avg_cost == Decimal("133.33")
    assert res.value_now == Decimal("3000")          # 15 × 200
    assert res.pnl_pct == 50.0
    # lump-sum: 2000 el 05-jun a 100 → 20 u → 4000 hoy (le gana: subida pura)
    assert res.lump_sum_value_now == Decimal("4000")
    # buys[-months:] toma los meses MÁS recientes de la ventana: jul y ago
    assert res.first_buy_date.endswith("-07-05") and res.last_buy_date.endswith("-08-05")
    assert "not a prediction" in res.disclaimer.lower()


def test_backtest_dca_fee_reduces_qty() -> None:
    closes = [100.0] * 40
    client = _client_with(closes, dt.date(2024, 6, 1))
    res = backtest_dca(client, "BTCUSDT", 1000, 1, day_of_month=5, fee=0.001)
    assert res.accumulated_qty == Decimal("9.99")    # (1000·0.999)/100


def test_backtest_dca_validates() -> None:
    c = MagicMock()
    for kwargs, match in [
        (dict(monthly_quote=1000, months=0), "months"),
        (dict(monthly_quote=0, months=2), "monthly_quote"),
        (dict(monthly_quote=1, months=2, day_of_month=31), "day_of_month"),
        (dict(monthly_quote=1, months=2, fee=0.5), "fee"),
    ]:
        with pytest.raises(ValueError, match=match):
            backtest_dca(c, "BTCUSDT", **kwargs)
    c.get_klines.assert_not_called()


# --- Harvest (verificado a mano) ---

def test_backtest_harvest_two_levels_hand_computed() -> None:
    # sube 100→120→160→200: nivel 110 (vende 50%) y 150 (vende 50% del restante)
    closes = [100.0, 120.0, 160.0, 200.0]
    client = _client_with(closes, dt.date(2024, 6, 1))
    res = backtest_harvest(client, "BTCUSDT", initial_qty=10,
                           grid=[{"level": 110, "sell_pct": 50},
                                 {"level": 150, "sell_pct": 50}],
                           start="2024-06-01", fee=0.0)
    assert len(res.fills) == 2
    # fill 1: 5 u @110 = 550 · fill 2: 2.5 u @150 = 375 · quedan 2.5 u
    assert res.fills[0].qty_sold == Decimal("5") and res.fills[0].proceeds == Decimal("550")
    assert res.fills[1].qty_sold == Decimal("2.5") and res.fills[1].proceeds == Decimal("375")
    assert res.remaining_qty == Decimal("2.5")
    assert res.total_proceeds == Decimal("925")
    assert res.final_value == Decimal("1425")        # 925 + 2.5×200
    assert res.pure_hold_value == Decimal("2000")    # en subida pura, hold gana — honesto
    # cada nivel dispara UNA vez
    assert len({f.level for f in res.fills}) == 2


def test_backtest_harvest_no_double_fire_and_validates() -> None:
    closes = [100.0, 120.0, 90.0, 130.0]             # re-cruza el 110: NO re-dispara
    client = _client_with(closes, dt.date(2024, 6, 1))
    res = backtest_harvest(client, "BTCUSDT", 10, [{"level": 110, "sell_pct": 10}],
                           start="2024-06-01")
    assert len(res.fills) == 1
    c = MagicMock()
    with pytest.raises(ValueError, match="initial_qty"):
        backtest_harvest(c, "BTCUSDT", 0, [{"level": 1, "sell_pct": 1}])
    with pytest.raises(ValueError, match="grid"):
        backtest_harvest(c, "BTCUSDT", 1, [])
    with pytest.raises(ValueError, match="sell_pct"):
        backtest_harvest(c, "BTCUSDT", 1, [{"level": 100, "sell_pct": 0}])
