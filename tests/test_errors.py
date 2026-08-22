from kainext_binance_mcp.errors import map_binance_error, scrub_secrets


def test_maps_known_codes():
    assert "insufficient funds" in map_binance_error(-2010, "Account has insufficient balance").lower()
    assert "filter" in map_binance_error(-1013, "Filter failure: LOT_SIZE").lower()
    assert "clock" in map_binance_error(-1021, "Timestamp ... recvWindow").lower()
    assert "cancelable" in map_binance_error(-2011, "Unknown order sent").lower()

def test_unknown_code_keeps_code_and_msg():
    out = map_binance_error(-9999, "weird")
    assert "-9999" in out and "weird" in out

def test_scrub_removes_api_key():
    text = "error X-MBX-APIKEY: abcSECRET123 in headers"
    assert "abcSECRET123" not in scrub_secrets(text, secrets=["abcSECRET123"])


def test_run_guarded_maps_and_scrubs():
    """Contrato de error único: excepción de python-binance sale como ToolExecutionError
    con mensaje mapeado y sin secretos."""
    import pytest

    from kainext_binance_mcp.errors import ToolExecutionError, run_guarded

    class FakeBinanceError(Exception):
        def __init__(self) -> None:
            self.code = -1003
            self.message = "banned, key=SECRETKEY99"

    def boom():
        raise FakeBinanceError()

    with pytest.raises(ToolExecutionError) as exc:
        run_guarded(lambda: ["SECRETKEY99"], boom)
    msg = str(exc.value)
    assert "SECRETKEY99" not in msg and "rate limit" in msg.lower()


def test_run_guarded_valueerror_keeps_message():
    import pytest

    from kainext_binance_mcp.errors import ToolExecutionError, run_guarded

    def bad():
        raise ValueError("invalid interval '5x'")

    with pytest.raises(ToolExecutionError, match="invalid interval"):
        run_guarded(lambda: [], bad)


def test_run_guarded_returns_value():
    from kainext_binance_mcp.errors import run_guarded
    assert run_guarded(lambda: [], lambda: 42) == 42


def test_strategy_literal_matches_backtest_strategies():
    """server.Strategy (Literal, viaja al schema) debe calzar con backtest.STRATEGIES."""
    from typing import get_args

    from kainext_binance_mcp import backtest as bt
    from kainext_binance_mcp.server import Strategy
    assert set(get_args(Strategy)) == set(bt.STRATEGIES)
