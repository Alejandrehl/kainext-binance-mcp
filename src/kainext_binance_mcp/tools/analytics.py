"""Capa 6 — frameworks de análisis como tools (read-only, spec Analyst Edition).

Los cálculos son objetivos; la INTERPRETACIÓN vive en los resources `kb://…` que cada
docstring de tool referencia. Sin datos personales embebidos: costo base, impuestos y
spread son SIEMPRE parámetros del usuario (producto público).
"""
from __future__ import annotations

import math
import time
from decimal import Decimal
from typing import TYPE_CHECKING

from kainext_binance_mcp import marketwide
from kainext_binance_mcp.klines import fetch_klines
from kainext_binance_mcp.models import (
    AssetRisk,
    CycleAnalysis,
    PortfolioPosition,
    PortfolioReport,
    RiskReport,
    validate_symbol,
)
from kainext_binance_mcp.tools import read as read_tools

if TYPE_CHECKING:
    from binance.client import Client

CYCLE_DISCLAIMER = (
    "Objective cycle inputs from n~4 historical cycles — a base rate, not a law. "
    "Interpret with kb://frameworks/cycle-analysis; output a phase with uncertainty, "
    "never a price target. Not financial advice."
)
PORTFOLIO_DISCLAIMER = (
    "Valuation snapshot. Net break-even math excludes local-currency effects (model it "
    "separately for your jurisdiction). Sizing doctrine: kb://discipline. Not financial advice."
)
RISK_DISCLAIMER = (
    "Historical realized metrics — the future can be worse than the worst backtest window. "
    "The actionable lever is position SIZE (kb://discipline rule 2). Not financial advice."
)

# Halving #5: estimación por altura de bloque (bloque 1.050.000, ~144 bloques/día).
EST_NEXT_HALVING = "~April 2028 (block 1,050,000; block-height based, date drifts)"

_STABLES = frozenset({"USDT", "USDC", "FDUSD", "TUSD", "DAI", "BUSD"})


def analyze_cycle(client: Client, symbol: str = "BTCUSDT") -> CycleAnalysis:
    """Inputs de posición de ciclo: Mayer Multiple (precio/MA200d), drawdown vs ATH
    (ATH de CoinGecko — sólo BTC), distancia al halving."""
    validate_symbol(symbol)
    notes: list[str] = []
    df = fetch_klines(client, symbol, "1d", 200)
    closes = df["close"].astype(float)
    price = Decimal(str(df["close"].iloc[-1]))
    ma200: Decimal | None = None
    mayer: float | None = None
    if len(closes) >= 200:
        ma_val = float(closes.tail(200).mean())
        ma200 = Decimal(str(round(ma_val, 2)))
        mayer = round(float(closes.iloc[-1]) / ma_val, 4) if ma_val > 0 else None
    else:
        notes.append(f"only {len(closes)} daily candles available; MA200 not computed")

    ath: Decimal | None = None
    dd_pct: float | None = None
    if symbol.startswith("BTC"):
        ms = marketwide.get_market_structure()
        ath = ms.btc_ath_usd
        dd_pct = ms.btc_ath_change_pct
        notes.extend(ms.notes)
    else:
        notes.append("ATH/drawdown only computed for BTC (CoinGecko source)")

    return CycleAnalysis(symbol=symbol, price=price, ma200d=ma200, mayer_multiple=mayer,
                         ath_usd=ath, drawdown_from_ath_pct=dd_pct,
                         est_next_halving=EST_NEXT_HALVING, notes=notes,
                         as_of=int(time.time() * 1000), disclaimer=CYCLE_DISCLAIMER)


def analyze_portfolio(client: Client,
                      cost_basis: dict[str, float] | None = None,
                      tax_rate: float = 0.0,
                      cashout_spread: float = 0.0) -> PortfolioReport:
    """Valoriza los balances live; concentración; PNL y break-even NETO si el usuario
    aporta `cost_basis` (por activo, en USDT) + su `tax_rate`/`cashout_spread`."""
    if not 0.0 <= tax_rate < 1.0:
        raise ValueError("tax_rate must be in [0, 1)")
    if not 0.0 <= cashout_spread < 1.0:
        raise ValueError("cashout_spread must be in [0, 1)")
    if tax_rate + cashout_spread >= 1.0:
        raise ValueError("tax_rate + cashout_spread must be < 1")
    notes: list[str] = []
    balances = read_tools.get_balance(client)
    positions: list[PortfolioPosition] = []
    total = Decimal("0")
    for b in balances:
        amount = b.free + b.locked
        price: Decimal | None = None
        if b.asset in _STABLES:
            price = Decimal("1")
        else:
            try:
                t = client.get_symbol_ticker(symbol=f"{b.asset}USDT")
                price = Decimal(t["price"])
            except Exception as e:  # noqa: BLE001 — activo sin par USDT: se reporta, no se cae
                notes.append(f"{b.asset}: no USDT pair ({type(e).__name__}); left unvalued")
        value = amount * price if price is not None else None
        if value is not None:
            total += value
        cb = None
        pnl = None
        if cost_basis and b.asset in cost_basis:
            cb = Decimal(str(cost_basis[b.asset]))
            if price is not None and cb > 0:
                pnl = round(float(price / cb - 1) * 100, 2)
        positions.append(PortfolioPosition(asset=b.asset, amount=amount, price_usdt=price,
                                           value_usdt=value, weight_pct=None,
                                           cost_basis=cb, pnl_pct=pnl))
    if total > 0:
        positions = [p.model_copy(update={
            "weight_pct": round(float(p.value_usdt / total) * 100, 2)
            if p.value_usdt is not None else None}) for p in positions]
    top = max((p.weight_pct for p in positions if p.weight_pct is not None), default=None)

    breakeven_note: str | None = None
    if cost_basis and (tax_rate > 0 or cashout_spread > 0):
        # P tal que P*(1-spread) - tax*(P-C) = C  =>  P = C*(1-tax) / (1-spread-tax).
        parts = []
        for asset, c in cost_basis.items():
            p_net = c * (1 - tax_rate) / (1 - cashout_spread - tax_rate)
            parts.append(f"{asset}: gross {c:,.2f} -> net ~{p_net:,.2f} USDT")
        breakeven_note = ("Net break-even (P*(1-spread) - tax*(P-C) = C; excludes "
                          "local-currency effects): " + "; ".join(parts))

    return PortfolioReport(positions=positions, total_value_usdt=total,
                           top_concentration_pct=top, net_breakeven_note=breakeven_note,
                           notes=notes, as_of=int(time.time() * 1000),
                           disclaimer=PORTFOLIO_DISCLAIMER)


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]


def _ann_vol_pct(rets: list[float]) -> float | None:
    if len(rets) < 5:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(365) * 100, 2)


def _max_drawdown_pct(closes: list[float]) -> float | None:
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for c in closes:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1)
    return round(worst * 100, 2)


def _corr(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 5:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if va == 0 or vb == 0:
        return None
    return round(cov / (va * vb), 3)


def assess_risk(client: Client, symbols: list[str] | None = None) -> RiskReport:
    """Vol realizada 30/90d, max drawdown (ventana 90d) y correlación con BTC por activo.
    Sin `symbols`: usa los activos en cartera con par USDT (excluye stables)."""
    notes: list[str] = []
    if symbols is None:
        held = read_tools.get_balance(client)
        symbols = [f"{b.asset}USDT" for b in held if b.asset not in _STABLES]
        if not symbols:
            notes.append("no non-stable holdings; pass symbols explicitly")
    for s in symbols:
        validate_symbol(s)

    btc_rets: list[float] | None = None
    try:
        btc_closes = fetch_klines(client, "BTCUSDT", "1d", 91)["close"].astype(float).tolist()
        btc_rets = _returns(btc_closes)
    except Exception as e:  # noqa: BLE001 — sin BTC no hay correlación, el resto sigue
        notes.append(f"BTCUSDT history unavailable ({type(e).__name__}); no correlations")

    assets: list[AssetRisk] = []
    for sym in symbols:
        try:
            closes = fetch_klines(client, sym, "1d", 91)["close"].astype(float).tolist()
        except Exception as e:  # noqa: BLE001 — un símbolo malo no tumba el reporte
            notes.append(f"{sym}: history unavailable ({type(e).__name__})")
            continue
        rets = _returns(closes)
        assets.append(AssetRisk(
            symbol=sym,
            realized_vol_30d_pct=_ann_vol_pct(rets[-30:]),
            realized_vol_90d_pct=_ann_vol_pct(rets),
            max_drawdown_pct=_max_drawdown_pct(closes),
            correlation_btc_90d=(_corr(rets, btc_rets)
                                 if btc_rets is not None and sym != "BTCUSDT" else
                                 (1.0 if sym == "BTCUSDT" else None)),
        ))
    return RiskReport(assets=assets, notes=notes, as_of=int(time.time() * 1000),
                      disclaimer=RISK_DISCLAIMER)
