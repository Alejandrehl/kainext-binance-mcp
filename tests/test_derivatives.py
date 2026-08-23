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
        {"symbol": "BTCUSDT", "fundingTime": 1704067200000, "fundingRate": "0.00010000"},
        {"symbol": "BTCUSDT", "fundingTime": 1704096000000, "fundingRate": "0.00012000"}]
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


def test_funding_events_keep_their_timestamps():
    """Sin `fundingTime` la serie no sirve para alinear el accrual con las velas.

    El wrapper aplanaba el historico a list[float] y tiraba la hora. `funding_history`
    se mantiene por compatibilidad con lo ya desplegado; `funding_events` es lo usable.
    """
    client = _client()
    snap = get_derivatives(client, "BTCUSDT")
    assert [e.funding_time for e in snap.funding_events] == [1704067200000, 1704096000000]
    assert [e.funding_rate for e in snap.funding_events] == [0.0001, 0.00012]
    assert snap.funding_history == [0.0001, 0.00012], "el campo viejo no puede cambiar"


def test_funding_window_is_forwarded_to_binance():
    """Acotar a una ventana concreta, en vez de "las ultimas N"."""
    client = _client()
    get_derivatives(client, "BTCUSDT", start_time=1_000, end_time=2_000)
    _, kwargs = client.futures_funding_rate.call_args
    assert kwargs["startTime"] == 1_000 and kwargs["endTime"] == 2_000


def test_window_without_bounds_sends_no_time_args():
    client = _client()
    get_derivatives(client, "BTCUSDT")
    _, kwargs = client.futures_funding_rate.call_args
    assert "startTime" not in kwargs and "endTime" not in kwargs


def test_inverted_window_is_rejected():
    with pytest.raises(ValueError, match="start_time"):
        get_derivatives(_client(), "BTCUSDT", start_time=2_000, end_time=1_000)
