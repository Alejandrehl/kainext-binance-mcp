"""Cobertura del wiring de tools del MCP server (_register_tools + _make_estimator).

Cada @mcp.tool() delega en funciones ya testeadas; acá verificamos que el cableado
(qué dependencia recibe cada tool, con qué args) es correcto, invocando la función
subyacente (`.fn`) que FastMCP registró. El server NUNCA ejecuta: las write delegan
en el confirmador vía ipc."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from kainext_binance_mcp import server as srv


def _register(client, ipc, market, *, is_testnet=True):
    # Aísla el registro en una FastMCP nueva por test (no contamina el módulo global).
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("test")
    srv.mcp = mcp
    srv._register_tools(client, ipc, market, is_testnet=is_testnet)
    return mcp._tool_manager


def _fn(tm, name):
    return tm.get_tool(name).fn


def test_make_estimator_closures_call_client():
    client = MagicMock()
    client.get_symbol_info.return_value = {
        "symbol": "BTCUSDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
            {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.0001"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ],
    }
    client.get_symbol_ticker.return_value = {"price": "50000.0"}
    est = srv._make_estimator(client)
    order = MagicMock(symbol="BTCUSDT", type="MARKET", price=None,
                      quote_quantity=Decimal("100"), quantity=None, env="testnet")
    preview = est.estimate(order)  # ejercita get_filters + get_price
    assert preview.env == "testnet"
    client.get_symbol_info.assert_called_with("BTCUSDT")
    client.get_symbol_ticker.assert_called_with(symbol="BTCUSDT")


def test_read_tools_delegate_to_client():
    client = MagicMock()
    client.get_account.return_value = {
        "balances": [{"asset": "BTC", "free": "1", "locked": "0"}],
        "canTrade": True, "commissionRates": {}, "accountType": "SPOT"}
    client.get_symbol_ticker.return_value = {"symbol": "BTCUSDT", "price": "50000"}
    client.get_open_orders.return_value = []
    client.get_all_orders.return_value = []
    tm = _register(client, MagicMock(), MagicMock(), is_testnet=True)

    assert _fn(tm, "binance_get_balance")()[0].asset == "BTC"
    assert _fn(tm, "binance_get_price")("BTCUSDT").price == Decimal("50000")
    assert _fn(tm, "binance_get_open_orders")() == []
    assert _fn(tm, "binance_get_order_history")("BTCUSDT") == []
    assert _fn(tm, "binance_get_account_info")().can_trade is True


def test_write_tools_delegate_to_ipc_and_never_execute():
    client = MagicMock()
    ipc = MagicMock()
    ipc.register.return_value = ("iid-1", 123)
    ipc.register_cancel.return_value = ("iid-2", 456)
    ipc.status.return_value = {"intent_id": "iid-1", "state": "pending",
                               "result": None, "error": None}
    client.get_order.return_value = {"status": "NEW"}
    from kainext_binance_mcp.models import OrderPreview
    market = MagicMock()
    market.estimate.return_value = OrderPreview(
        effective_qty=Decimal("0.0002"), price=None, est_notional=Decimal("10"),
        est_commission=Decimal("0.01"), env="testnet", feasible=True)
    tm = _register(client, ipc, market, is_testnet=True)

    prop = _fn(tm, "binance_spot_order_propose")(
        symbol="BTCUSDT", side="BUY", type="MARKET", env="testnet",
        quote_quantity=Decimal("10"))
    assert prop.intent_id == "iid-1"
    ipc.register.assert_called_once()
    client.create_order.assert_not_called()  # el server NUNCA ejecuta

    st = _fn(tm, "binance_spot_order_status")("iid-1")
    assert st.state == "pending"

    cprop = _fn(tm, "binance_cancel_order_propose")(symbol="BTCUSDT", order_id=7, env="testnet")
    assert cprop.intent_id == "iid-2"
    ipc.register_cancel.assert_called_once()

    cst = _fn(tm, "binance_cancel_order_status")("iid-1")
    assert cst.state == "pending"


def _binance_klines(n=40):
    base = 1717000000000
    rows = []
    for i in range(n):
        price = 100.0 + i
        rows.append([base + i * 3600000, f"{price:.2f}", f"{price + 1:.2f}",
                     f"{price - 1:.2f}", f"{price + 0.5:.2f}", "10.0",
                     base + i * 3600000 + 3599999, "1000.0", 50, "5.0", "500.0", "0"])
    return rows


def test_capa2_marketdata_tools_delegate_to_client():
    """Las 4 tools read-only de capa 2 quedan registradas y delegan en el client read."""
    client = MagicMock()
    client.get_klines.return_value = _binance_klines(40)
    client.get_ticker.return_value = {
        "symbol": "BTCUSDT", "priceChangePercent": "2.5", "highPrice": "51000",
        "lowPrice": "49000", "volume": "1234.5", "lastPrice": "50500"}
    tm = _register(client, MagicMock(), MagicMock(), is_testnet=True)

    from kainext_binance_mcp.models import (
        BacktestResult,
        IndicatorResult,
        Kline,
        Ticker24h,
    )

    klines = _fn(tm, "binance_get_klines")("BTCUSDT", "1h", 40)
    assert len(klines) == 40 and isinstance(klines[0], Kline)

    ticker = _fn(tm, "binance_get_ticker_24h")("BTCUSDT")
    assert isinstance(ticker, Ticker24h) and ticker.symbol == "BTCUSDT"

    indi = _fn(tm, "binance_compute_indicators")("BTCUSDT", "1h", ["rsi", "ema"], 40)
    assert isinstance(indi, IndicatorResult) and "rsi" in indi.indicators

    res = _fn(tm, "binance_backtest")("BTCUSDT", "1h", "ema_cross", 40)
    assert isinstance(res, BacktestResult) and res.strategy == "ema_cross"

    # Read-only: jamás coloca ni cancela órdenes.
    client.create_order.assert_not_called()
    client.cancel_order.assert_not_called()


def test_capa3_news_tools_delegate_without_client(monkeypatch):
    """Las 2 tools read-only de capa 3 quedan registradas y delegan en tools/news.

    No reciben client (RSS público). Mockeamos el registro de fuentes para no tocar red.
    """
    from kainext_binance_mcp.models import NewsItem, SentimentResult
    from kainext_binance_mcp.news import fetch as fetchmod
    from kainext_binance_mcp.tools import news as news_tools

    class _FakeSource:
        name = "coindesk"

        def fetch(self):
            now = 2_000_000
            return [
                NewsItem(title="Bitcoin surges", summary="", source="coindesk",
                         published=now - 100, url="https://e/x", assets=["BTC"], sentiment=0.5),
                NewsItem(title="ETH news", summary="", source="coindesk",
                         published=now - 200, url="https://e/y", assets=["ETH"], sentiment=-0.2),
            ]

    fake_registry = {"coindesk": _FakeSource()}
    monkeypatch.setattr(news_tools, "SOURCES", fake_registry)
    # Cache de módulo fresco + reloj fijo (sin red, determinista).
    monkeypatch.setattr(news_tools, "_MODULE_CACHE",
                        fetchmod.NewsCache(ttl_seconds=300, clock=lambda: 1000.0))
    monkeypatch.setattr(news_tools.time, "time", lambda: 2_000_000)

    tm = _register(MagicMock(), MagicMock(), MagicMock(), is_testnet=True)

    news = _fn(tm, "binance_get_news")(asset="BTC")
    assert news and all(isinstance(i, NewsItem) for i in news)
    assert all("BTC" in i.assets for i in news)

    sent = _fn(tm, "binance_get_sentiment")("BTC", 24)
    assert isinstance(sent, SentimentResult)
    assert sent.asset == "BTC"
    assert sent.n_items == 1
    assert sent.disclaimer.strip()


def test_capa4_signal_tools_delegate_to_client(monkeypatch):
    """Las 2 tools de capa 4 quedan registradas, delegan en el client read (capa 2) y el
    sentiment (capa 3, mockeado para no tocar red), y NUNCA ejecutan."""
    from kainext_binance_mcp.models import SentimentResult, Signal
    from kainext_binance_mcp.tools import signals as signals_tools

    def _fake_sentiment(asset, **_):
        return SentimentResult(asset=asset, window_hours=24, score=0.4,
                               n_items=2, sample=[], disclaimer="crudo")

    monkeypatch.setattr(signals_tools.news_tools, "get_sentiment", _fake_sentiment)

    client = MagicMock()
    client.get_klines.return_value = _binance_klines(60)  # tendencia alcista
    tm = _register(client, MagicMock(), MagicMock(), is_testnet=True)

    sig = _fn(tm, "binance_generate_signal")("BTCUSDT", "1h")
    assert isinstance(sig, Signal) and sig.symbol == "BTCUSDT"
    assert -1.0 <= sig.score <= 1.0 and len(sig.factors) == 5

    ranked = _fn(tm, "binance_scan_signals")(["BTCUSDT", "ETHUSDT"], "1h")
    assert all(isinstance(s, Signal) for s in ranked) and len(ranked) == 2
    # Rankeadas por score descendente.
    assert [s.score for s in ranked] == sorted((s.score for s in ranked), reverse=True)

    # Read-only / PROPONE: jamás coloca ni cancela órdenes.
    client.create_order.assert_not_called()
    client.cancel_order.assert_not_called()


def test_analyst_tools_delegate_and_never_execute():
    """Los 5 shims v1.1 delegan (capa 5/6) y jamás tocan órdenes."""
    from decimal import Decimal
    from unittest.mock import MagicMock, patch

    client = MagicMock()
    client.get_account.return_value = {"balances": []}
    tm = _register(client, MagicMock(), MagicMock())
    names = {t.name for t in tm.list_tools()}
    assert {"binance_get_derivatives", "binance_get_market_structure",
            "binance_analyze_cycle", "binance_analyze_portfolio",
            "binance_assess_risk", "binance_backtest_dca",
            "binance_backtest_harvest"} <= names
    assert len(names) == 25  # el conteo del producto: si cambia, actualizar docs/README

    rep = _fn(tm, "binance_analyze_portfolio")()
    assert rep.total_value_usdt == Decimal("0")

    with patch("kainext_binance_mcp.server._get_market_structure") as gm:
        gm.return_value = MagicMock()
        _fn(tm, "binance_get_market_structure")()
        gm.assert_called_once()

    client.create_order.assert_not_called()
    client.cancel_order.assert_not_called()
