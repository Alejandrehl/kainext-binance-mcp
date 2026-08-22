"""Capa 5: derivados públicos (funding/OI/mark) con client mockeado."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kainext_binance_mcp.derivatives import get_derivatives


def _client() -> MagicMock:
    c = MagicMock()
    c.futures_mark_price.return_value = {
        "markPrice": "77314.05", "indexPrice": "77307.28",
        "lastFundingRate": "0.00010000", "nextFundingTime": 1787443200000}
    c.futures_funding_rate.return_value = [
        {"fundingRate": "0.00010000"}, {"fundingRate": "0.00012000"}]
    c.futures_open_interest.return_value = {"openInterest": "106637.083"}
    return c


def test_snapshot_maps_fields() -> None:
    snap = get_derivatives(_client(), "BTCUSDT")
    assert snap.mark_price == Decimal("77314.05")
    assert snap.index_price == Decimal("77307.28")
    assert snap.last_funding_rate == 0.0001
    assert snap.funding_history == [0.0001, 0.00012]
    assert snap.open_interest == Decimal("106637.083")
    assert snap.next_funding_time == 1787443200000
    assert snap.disclaimer and "testnet" in snap.disclaimer.lower()


def test_validates_inputs_before_any_call() -> None:
    c = _client()
    with pytest.raises(ValueError, match="invalid symbol"):
        get_derivatives(c, 'BTC"USDT')
    with pytest.raises(ValueError, match="funding_limit"):
        get_derivatives(c, "BTCUSDT", funding_limit=0)
    c.futures_mark_price.assert_not_called()
