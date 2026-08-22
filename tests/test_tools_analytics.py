"""Capa 6: analytics (cycle, portfolio, risk) con client mockeado."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kainext_binance_mcp.models import MarketStructure
from kainext_binance_mcp.tools.analytics import (
    _ann_vol_pct,
    _corr,
    _max_drawdown_pct,
    _returns,
    analyze_cycle,
    analyze_portfolio,
    assess_risk,
)


def _klines(closes: list[float]) -> list[list[object]]:
    out = []
    for i, c in enumerate(closes):
        out.append([i * 86_400_000, str(c), str(c * 1.01), str(c * 0.99), str(c),
                    "10", (i + 1) * 86_400_000 - 1, "1000", 100, "5", "500", "0"])
    return out


def _ms(**overrides) -> MarketStructure:
    base = dict(fear_greed=71, fear_greed_label="Greed", fear_greed_week=[71],
                btc_dominance_pct=58.0, total_market_cap_usd=2.6e12,
                btc_ath_usd=Decimal("126080"), btc_ath_date="2025-10-06",
                btc_ath_change_pct=-38.7, mempool_fee_fast_sat_vb=3,
                hashrate_avg_ehs=800.0, notes=[], as_of=1, disclaimer="d")
    base.update(overrides)
    return MarketStructure(**base)


# --- cycle ---

def test_cycle_computes_mayer_and_uses_ath() -> None:
    c = MagicMock()
    c.get_klines.return_value = _klines([100.0] * 199 + [120.0])
    with patch("kainext_binance_mcp.tools.analytics.marketwide") as mw:
        mw.get_market_structure.return_value = _ms()
        res = analyze_cycle(c, "BTCUSDT")
    assert res.price == Decimal("120.0")
    assert res.mayer_multiple == pytest.approx(120.0 / ((199 * 100 + 120) / 200), rel=1e-3)
    assert res.ath_usd == Decimal("126080") and res.drawdown_from_ath_pct == -38.7
    assert "halving" in res.est_next_halving.lower() or "block" in res.est_next_halving.lower()
    assert res.disclaimer


def test_cycle_non_btc_has_no_ath_and_short_history_no_mayer() -> None:
    c = MagicMock()
    c.get_klines.return_value = _klines([10.0] * 50)
    res = analyze_cycle(c, "LINKUSDT")
    assert res.ath_usd is None and res.mayer_multiple is None
    assert any("ATH" in n for n in res.notes) and any("MA200" in n for n in res.notes)


# --- portfolio ---

def _balances(client: MagicMock, rows: list[tuple[str, str]]) -> None:
    client.get_account.return_value = {
        "balances": [{"asset": a, "free": amt, "locked": "0"} for a, amt in rows]}


def test_portfolio_values_and_concentration_and_breakeven() -> None:
    c = MagicMock()
    _balances(c, [("BTC", "0.5"), ("USDT", "100")])
    c.get_symbol_ticker.return_value = {"price": "80000"}
    rep = analyze_portfolio(c, cost_basis={"BTC": 100000.0}, tax_rate=0.35,
                            cashout_spread=0.02)
    btc = next(p for p in rep.positions if p.asset == "BTC")
    assert btc.value_usdt == Decimal("40000") and btc.pnl_pct == -20.0
    assert rep.total_value_usdt == Decimal("40100")
    assert btc.weight_pct == pytest.approx(99.75, abs=0.01)
    assert rep.top_concentration_pct == pytest.approx(99.75, abs=0.01)
    # P = C*(1-t)/(1-s-t) = 100000*0.65/0.63
    assert rep.net_breakeven_note is not None
    assert "103,174" in rep.net_breakeven_note


def test_portfolio_unpriced_asset_degrades_with_note() -> None:
    c = MagicMock()
    _balances(c, [("WEIRD", "5")])
    c.get_symbol_ticker.side_effect = OSError("no pair")
    rep = analyze_portfolio(c)
    assert rep.positions[0].value_usdt is None
    assert any("WEIRD" in n for n in rep.notes)
    assert rep.total_value_usdt == Decimal("0")


def test_portfolio_validates_params() -> None:
    c = MagicMock()
    with pytest.raises(ValueError, match="tax_rate"):
        analyze_portfolio(c, tax_rate=1.0)
    with pytest.raises(ValueError, match="cashout_spread"):
        analyze_portfolio(c, cashout_spread=-0.1)
    with pytest.raises(ValueError, match="< 1"):
        analyze_portfolio(c, tax_rate=0.6, cashout_spread=0.5)
    c.get_account.assert_not_called()


# --- risk helpers (puros) ---

def test_risk_helpers() -> None:
    closes = [100.0, 110.0, 99.0, 121.0]
    rets = _returns(closes)
    assert rets == pytest.approx([0.1, -0.1, 0.2222], abs=1e-3)
    assert _ann_vol_pct([0.01] * 4) is None          # < 5 muestras
    assert _ann_vol_pct([0.01, -0.02, 0.03, -0.01, 0.02]) is not None
    assert _max_drawdown_pct([100, 80, 90, 60]) == -40.0
    assert _corr([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == 1.0
    assert _corr([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None  # varianza cero


def test_assess_risk_defaults_to_holdings_and_degrades() -> None:
    c = MagicMock()
    _balances(c, [("BTC", "1"), ("USDT", "10")])
    c.get_klines.return_value = _klines([100.0 + i for i in range(91)])
    rep = assess_risk(c)
    assert [a.symbol for a in rep.assets] == ["BTCUSDT"]
    assert rep.assets[0].correlation_btc_90d == 1.0
    assert rep.assets[0].realized_vol_30d_pct is not None
    # símbolo inválido en input explícito
    with pytest.raises(ValueError, match="invalid symbol"):
        assess_risk(c, symbols=["bad symbol"])
