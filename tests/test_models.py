from decimal import Decimal
import pytest
from pydantic import ValidationError
from kainext_binance_mcp.models import CanonicalOrder

def test_limit_requires_price():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.001"), time_in_force="GTC", env="testnet")  # sin price

def test_market_rejects_price_and_tif():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0.001"), price=Decimal("50000"), env="testnet")

def test_xor_quantity_quote():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0.001"), quote_quantity=Decimal("50"), env="testnet")
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET", env="testnet")  # ninguno

def test_quote_only_market():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quote_quantity=Decimal("50"), price=Decimal("50000"),
                       time_in_force="GTC", env="testnet")

def test_valid_limit_ok():
    o = CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.001"), price=Decimal("50000"),
                       time_in_force="GTC", env="testnet")
    assert o.quantity == Decimal("0.001")

def test_rejects_non_positive():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0"), env="testnet")

def test_limit_requires_time_in_force():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       quantity=Decimal("0.001"), price=Decimal("50000"),
                       env="testnet")  # sin time_in_force

def test_limit_requires_quantity():
    # LIMIT con price+tif pero sin quantity ni quote_quantity → línea "LIMIT requiere quantity"
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="LIMIT",
                       price=Decimal("50000"), time_in_force="GTC", env="testnet")

def test_market_rejects_time_in_force_alone():
    with pytest.raises(ValidationError):
        CanonicalOrder(symbol="BTCUSDT", side="BUY", type="MARKET",
                       quantity=Decimal("0.001"), time_in_force="GTC", env="testnet")
