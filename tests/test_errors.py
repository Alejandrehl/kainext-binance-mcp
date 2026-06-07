from kainext_binance_mcp.errors import map_binance_error, scrub_secrets

def test_maps_known_codes():
    assert "fondos insuficientes" in map_binance_error(-2010, "Account has insufficient balance").lower()
    assert "filtro" in map_binance_error(-1013, "Filter failure: LOT_SIZE").lower()
    assert "reloj" in map_binance_error(-1021, "Timestamp ... recvWindow").lower()
    assert "cancelable" in map_binance_error(-2011, "Unknown order sent").lower()

def test_unknown_code_keeps_code_and_msg():
    out = map_binance_error(-9999, "weird")
    assert "-9999" in out and "weird" in out

def test_scrub_removes_api_key():
    text = "error X-MBX-APIKEY: abcSECRET123 in headers"
    assert "abcSECRET123" not in scrub_secrets(text, secrets=["abcSECRET123"])
