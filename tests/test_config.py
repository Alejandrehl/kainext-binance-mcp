import pytest

from kainext_binance_mcp.config import (
    ConfigError,
    load_confirmer_settings,
    load_server_settings,
)

BASE = {"BINANCE_ENV": "testnet", "BINANCE_READ_API_KEY": "k", "BINANCE_READ_API_SECRET": "s"}
CONFIRMER_BASE = {"BINANCE_ENV": "testnet", "BINANCE_TRADE_API_KEY": "k",
                  "BINANCE_TRADE_API_SECRET": "s"}

def test_ok():
    st = load_server_settings(BASE)
    assert st.env == "testnet" and st.is_testnet and st.api_key == "k"

def test_missing_env_aborts():
    with pytest.raises(ConfigError):
        load_server_settings({"BINANCE_READ_API_KEY": "k", "BINANCE_READ_API_SECRET": "s"})

def test_invalid_env_aborts():
    with pytest.raises(ConfigError):
        load_server_settings({**BASE, "BINANCE_ENV": "prod"})

def test_empty_or_whitespace_key_aborts():
    with pytest.raises(ConfigError):
        load_server_settings({**BASE, "BINANCE_READ_API_KEY": "   "})

def test_unexpanded_var_aborts():
    with pytest.raises(ConfigError):
        load_server_settings({**BASE, "BINANCE_READ_API_KEY": "${BINANCE_READ_API_KEY}"})

def test_mainnet():
    st = load_server_settings({**BASE, "BINANCE_ENV": "mainnet"})
    assert st.env == "mainnet" and not st.is_testnet


# --- load_confirmer_settings: usa las TRADE keys (spec §4.2b) -----------------

def test_confirmer_ok():
    st = load_confirmer_settings(CONFIRMER_BASE)
    assert st.env == "testnet" and st.is_testnet and st.api_key == "k" and st.api_secret == "s"

def test_confirmer_missing_env_aborts():
    with pytest.raises(ConfigError):
        load_confirmer_settings({"BINANCE_TRADE_API_KEY": "k", "BINANCE_TRADE_API_SECRET": "s"})

def test_confirmer_invalid_env_aborts():
    with pytest.raises(ConfigError):
        load_confirmer_settings({**CONFIRMER_BASE, "BINANCE_ENV": "prod"})

def test_confirmer_empty_or_whitespace_key_aborts():
    with pytest.raises(ConfigError):
        load_confirmer_settings({**CONFIRMER_BASE, "BINANCE_TRADE_API_KEY": "   "})

def test_confirmer_unexpanded_var_aborts():
    with pytest.raises(ConfigError):
        load_confirmer_settings(
            {**CONFIRMER_BASE, "BINANCE_TRADE_API_KEY": "${BINANCE_TRADE_API_KEY}"})

def test_confirmer_mainnet():
    st = load_confirmer_settings({**CONFIRMER_BASE, "BINANCE_ENV": "mainnet"})
    assert st.env == "mainnet" and not st.is_testnet
