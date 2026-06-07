from decimal import Decimal
import pytest

@pytest.fixture
def symbol_filters_btcusdt():
    from kainext_binance_mcp.market import SymbolFilters
    return SymbolFilters(
        symbol="BTCUSDT",
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.00001"),
        market_step_size=Decimal("0.00001"),
        min_notional=Decimal("5"),
    )
