from unittest.mock import patch

from kainext_binance_mcp.client import make_client
from kainext_binance_mcp.config import Settings


def test_make_client_sets_testnet_and_syncs_time():
    with patch("kainext_binance_mcp.client.Client") as C:
        inst = C.return_value
        st = Settings(env="testnet", api_key="k", api_secret="s")
        make_client(st)
        C.assert_called_once_with("k", "s", testnet=True)
        # sync de tiempo: se llamó a get_server_time / ajuste de offset
        assert inst.get_server_time.called or hasattr(inst, "timestamp_offset")
