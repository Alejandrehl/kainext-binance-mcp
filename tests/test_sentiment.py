"""Tests del sentiment léxico determinista + detección de activos (plan Task 1, spec §5/N5).

El léxico es propio (definido en ``sentiment.py``) y debe ser determinista, puro y sin red:
frases conocidas bull→>0, bear→<0, neutra→0; alias case-insensitive.
"""
from __future__ import annotations

from kainext_binance_mcp.news.sentiment import detect_assets, score_text


# --- score_text: rango y signo ---

def test_score_text_bullish_is_positive() -> None:
    s = score_text("Bitcoin surges to new highs, bullish rally")
    assert s > 0
    assert -1.0 <= s <= 1.0


def test_score_text_bearish_is_negative() -> None:
    s = score_text("Exchange hacked, market crash, lawsuit")
    assert s < 0
    assert -1.0 <= s <= 1.0


def test_score_text_neutral_is_zero() -> None:
    assert score_text("Bitcoin price update") == 0.0


def test_score_text_empty_is_zero() -> None:
    assert score_text("") == 0.0


def test_score_text_is_deterministic() -> None:
    text = "Massive adoption and ETF approved, but hack fears persist"
    assert score_text(text) == score_text(text)


def test_score_text_clamped_to_range() -> None:
    # Mucho término bull no debe pasar de 1.0.
    text = "surge rally breakout adoption bullish gains soar pump"
    s = score_text(text)
    assert -1.0 <= s <= 1.0


def test_score_text_case_insensitive() -> None:
    assert score_text("BULLISH RALLY SURGE") > 0
    assert score_text("CRASH HACK LAWSUIT") < 0


# --- detect_assets: alias y case-insensitive ---

def test_detect_assets_finds_eth_and_btc() -> None:
    found = detect_assets("Ethereum and BTC rally")
    assert "ETH" in found
    assert "BTC" in found


def test_detect_assets_case_insensitive() -> None:
    found = detect_assets("bitcoin and SOLANA pump")
    assert "BTC" in found
    assert "SOL" in found


def test_detect_assets_none_returns_empty() -> None:
    assert detect_assets("the stock market closed flat today") == []


def test_detect_assets_empty_string() -> None:
    assert detect_assets("") == []


def test_detect_assets_no_duplicates_and_sorted() -> None:
    found = detect_assets("Bitcoin BTC bitcoin BITCOIN")
    assert found == ["BTC"]


def test_detect_assets_word_boundary() -> None:
    # 'ada' dentro de 'Canada' no debe matchear ADA; 'Cardano' sí.
    assert "ADA" not in detect_assets("Canada regulates crypto")
    assert "ADA" in detect_assets("Cardano upgrade shipped")


def test_detect_assets_multiple() -> None:
    found = detect_assets("BNB, XRP, DOGE and ADA all moved today")
    for a in ("BNB", "XRP", "DOGE", "ADA"):
        assert a in found
