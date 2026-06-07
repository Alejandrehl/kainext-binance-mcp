import pytest
from kainext_binance_mcp.config import load_server_settings, ConfigError

BASE = {"BINANCE_ENV": "testnet", "BINANCE_READ_API_KEY": "k", "BINANCE_READ_API_SECRET": "s"}

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
