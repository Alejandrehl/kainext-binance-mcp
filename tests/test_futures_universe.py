"""Universo point-in-time: la defensa contra el sesgo de supervivencia.

Hoy cotizan 527 perpetuos USDT y el archivo tiene 986 simbolos. Si el universo son los
527 vivos, el backtest de momentum le pregunta al pasado usando la respuesta del futuro.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kainext_binance_mcp.futures.data import BinanceArchive
from kainext_binance_mcp.futures.universe import (
    Universe,
    has_denomination_multiplier,
    list_archive_symbols,
    usdt_perpetuals,
)

_NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _listing(symbols: list[str], token: str | None = None) -> str:
    prefixes = "".join(
        f"<CommonPrefixes><Prefix>data/futures/um/monthly/klines/{s}/</Prefix></CommonPrefixes>"
        for s in symbols
    )
    nxt = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    return f'<?xml version="1.0"?><ListBucketResult {_NS}>{prefixes}{nxt}</ListBucketResult>'


# ── Listado del archivo ──────────────────────────────────────────────────────────────

def test_listing_paginates_and_keeps_delisted_symbols() -> None:
    """Un solo page fetch dejaria fuera la mayoria del universo (986 > max-keys)."""
    pages = iter([_listing(["BTCUSDT", "AAPLUSDT"], token="tok+en/1"), _listing(["ETHUSDT"])])
    urls: list[str] = []

    def fetch(url: str) -> str:
        urls.append(url)
        return next(pages)

    assert list_archive_symbols(fetch) == ["AAPLUSDT", "BTCUSDT", "ETHUSDT"]
    assert len(urls) == 2
    assert "continuation-token=tok%2Ben%2F1" in urls[1], "el token debe ir URL-encodeado"


def test_quote_asset_filter_keeps_the_universe_comparable() -> None:
    """El archivo mezcla USDT/USDC/USD1/BTC; comparar retornos entre monedas no tiene sentido."""
    mixed = ["BTCUSDT", "BTCUSDC", "ETHUSD1", "ETHBTC", "SOLUSDT"]
    assert usdt_perpetuals(mixed) == ["BTCUSDT", "SOLUSDT"]


@pytest.mark.parametrize("symbol", ["1000PEPEUSDT", "1000SHIBUSDT", "1000000BOBUSDT"])
def test_denomination_multipliers_are_flagged(symbol: str) -> None:
    """Encadenar PEPE con 1000PEPE inventa un retorno de +99.900% que gana todo ranking."""
    assert has_denomination_multiplier(symbol)


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "AAPLUSDT"])
def test_normal_symbols_are_not_flagged(symbol: str) -> None:
    assert not has_denomination_multiplier(symbol)


# ── Pertenencia point-in-time ────────────────────────────────────────────────────────

def _panels(n_days: int = 200) -> tuple[pd.DataFrame, pd.DataFrame]:
    """LIVE cotiza siempre; DEAD se delista a mitad; NEW aparece tarde; THIN no tiene volumen."""
    idx = [1_577_836_800_000 + i * 86_400_000 for i in range(n_days)]
    closes = pd.DataFrame(index=idx, dtype="float64")
    volumes = pd.DataFrame(index=idx, dtype="float64")
    closes["LIVEUSDT"] = np.linspace(100, 200, n_days)
    closes["DEADUSDT"] = np.linspace(50, 10, n_days)
    closes.loc[idx[120]:, "DEADUSDT"] = np.nan          # delistado el dia 120
    closes["NEWUSDT"] = np.nan
    closes.loc[idx[150]:, "NEWUSDT"] = 5.0              # listado el dia 150
    closes["THINUSDT"] = 1.0
    for col in closes.columns:
        volumes[col] = np.where(closes[col].notna(), 5_000_000.0, np.nan)
    volumes["THINUSDT"] = np.where(closes["THINUSDT"].notna(), 1_000.0, np.nan)
    return closes, volumes


def test_delisted_symbol_is_a_member_before_it_dies_and_not_after() -> None:
    """El corazon del anti-survivorship: DEADUSDT existio y el ranking debe haberlo visto."""
    closes, volumes = _panels()
    before = Universe.members_at(closes, volumes, closes.index[119])
    after = Universe.members_at(closes, volumes, closes.index[130])
    assert "DEADUSDT" in before, "un simbolo vivo ese dia quedo fuera del universo"
    assert "DEADUSDT" not in after, "un simbolo delistado sigue en el universo"


def test_new_listing_needs_history_before_it_is_rankable() -> None:
    """Rankear por momentum de 90 dias a un simbolo con 5 dias de vida es ruido."""
    closes, volumes = _panels()
    assert "NEWUSDT" not in Universe.members_at(closes, volumes, closes.index[155])


def test_illiquid_symbols_are_excluded() -> None:
    """Sin filtro de liquidez, el decil ganador se llena de libros vacios."""
    closes, volumes = _panels()
    members = Universe.members_at(closes, volumes, closes.index[119])
    assert "THINUSDT" not in members and "LIVEUSDT" in members


def test_membership_uses_only_information_up_to_the_date() -> None:
    """Causalidad: lo que pasa despues de `when` no puede cambiar quien era miembro."""
    closes, volumes = _panels()
    when = closes.index[100]
    baseline = Universe.members_at(closes, volumes, when)

    futuro_c, futuro_v = closes.copy(), volumes.copy()
    futuro_c.loc[closes.index[150]:, :] = np.nan      # el futuro entero se borra
    futuro_v.loc[volumes.index[150]:, :] = np.nan
    assert Universe.members_at(futuro_c, futuro_v, when) == baseline


def test_unknown_date_yields_no_members() -> None:
    closes, volumes = _panels()
    assert Universe.members_at(closes, volumes, 1) == []


# ── Panel ancho ──────────────────────────────────────────────────────────────────────

def test_panel_marks_absent_symbols_as_nan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La ausencia es la que codifica alta y baja: no hace falta un registro de listings."""
    archive = BinanceArchive(root=tmp_path, fetch=lambda url: None)

    frames = {
        "AUSDT": pd.DataFrame({"open_time": [1, 2, 3], "close": [1.0, 2.0, 3.0],
                               "quote_volume": [9.0] * 3}),
        "BUSDT": pd.DataFrame({"open_time": [2, 3], "close": [5.0, 6.0],
                               "quote_volume": [9.0] * 2}),
        "CUSDT": pd.DataFrame(),
    }
    monkeypatch.setattr(archive, "load_klines",
                        lambda symbol, interval="1d", **kw: frames[symbol])

    closes, volumes = Universe(archive, ["AUSDT", "BUSDT", "CUSDT"]).load_panels(
        start=date(2020, 1, 1))
    assert list(closes.columns) == ["AUSDT", "BUSDT"], "un simbolo sin datos no crea columna"
    assert pd.isna(closes.loc[1, "BUSDT"]), "el dia previo al listado debe ser NaN"
    assert closes.loc[3, "BUSDT"] == 6.0
    assert volumes.shape == closes.shape
