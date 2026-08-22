from decimal import Decimal

from kainext_binance_mcp.market import (
    MarketEstimator,
    parse_symbol_filters,
    round_to_step,
    round_to_tick,
    validate_notional,
)
from kainext_binance_mcp.models import CanonicalOrder


def test_round_qty_floor_to_step():
    assert round_to_step(Decimal("0.123456"), Decimal("0.00001")) == Decimal("0.12345")

def test_round_price_to_tick():
    assert round_to_tick(Decimal("50000.017"), Decimal("0.01")) == Decimal("50000.01")

def test_step_zero_is_noop():
    assert round_to_step(Decimal("1.23"), Decimal("0")) == Decimal("1.23")

def test_tick_zero_is_noop():
    assert round_to_tick(Decimal("1.23"), Decimal("0")) == Decimal("1.23")

def test_notional_ok_and_fail():
    assert validate_notional(Decimal("0.001"), Decimal("50000"), Decimal("5")) is None
    assert "notional" in validate_notional(Decimal("0.00001"), Decimal("50000"), Decimal("5")).lower()


def test_parse_symbol_filters_from_exchange_info():
    """Construye SymbolFilters desde el dict de get_symbol_info (LOT_SIZE, MARKET_LOT_SIZE,
    NOTIONAL, PRICE_FILTER)."""
    info = {
        "symbol": "BTCUSDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
            {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.0001"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ],
    }
    f = parse_symbol_filters(info)
    assert f.symbol == "BTCUSDT"
    assert f.tick_size == Decimal("0.01")
    assert f.step_size == Decimal("0.00001")
    assert f.market_step_size == Decimal("0.0001")
    assert f.min_notional == Decimal("5")


def test_parse_symbol_filters_falls_back_to_lot_size_for_market_and_min_notional():
    """Sin MARKET_LOT_SIZE → usa LOT_SIZE; con MIN_NOTIONAL (legacy) en vez de NOTIONAL."""
    info = {
        "symbol": "ETHUSDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.0001"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
        ],
    }
    f = parse_symbol_filters(info)
    assert f.market_step_size == Decimal("0.0001")  # cae a LOT_SIZE
    assert f.min_notional == Decimal("10")


def test_estimate_market_quote_quantity_warns_and_derives_qty(symbol_filters_btcusdt):
    """MARKET con quote_quantity: agrega warning de slippage y deriva la qty efectiva
    (quote/precio redondeada al market_step_size). price queda None (no autoritativo)."""
    est = MarketEstimator(get_filters=lambda s: symbol_filters_btcusdt,
                          get_price=lambda s: Decimal("50000"))
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quote_quantity=Decimal("100"), env="testnet")
    p = est.estimate(o)
    assert p.price is None
    assert any("MARKET" in w for w in p.warnings)
    assert p.effective_qty == Decimal("0.002")  # 100/50000 = 0.002, ya múltiplo del step
    assert p.feasible
