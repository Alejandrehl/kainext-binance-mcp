from decimal import Decimal

from kainext_binance_mcp.market import MarketEstimator
from kainext_binance_mcp.models import CanonicalOrder


def _est(filters_btcusdt):
    return MarketEstimator(get_filters=lambda s: filters_btcusdt,
                           get_price=lambda s: Decimal("50000"))


def test_estimate_rounds_and_marks_feasible(symbol_filters_btcusdt):
    est = _est(symbol_filters_btcusdt)
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.0012345"), price=Decimal("50000.017"),
                       time_in_force="GTC", env="testnet")
    p = est.estimate(o)
    assert p.effective_qty == Decimal("0.00123") and p.price == Decimal("50000.01") and p.feasible


def test_estimate_infeasible_below_notional(symbol_filters_btcusdt):
    est = _est(symbol_filters_btcusdt)
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.00001"), price=Decimal("50000"),
                       time_in_force="GTC", env="testnet")
    p = est.estimate(o)
    assert not p.feasible and "notional" in (p.reason or "").lower()
