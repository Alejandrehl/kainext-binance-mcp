"""Capa de datos de futuros: sin red, con zips construidos a mano.

Los tres casos que importan no son de plomería: header por era, hueco del mes en curso,
y que la vela de hoy quede fuera. Los tres corrompen en silencio si están mal.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from kainext_binance_mcp.futures.data import (
    FUNDING_COLUMNS,
    KLINE_COLUMNS,
    BinanceArchive,
    days_between,
    default_cache_root,
    months_between,
    read_archive_csv,
)

_ROW = "1704067200000,42314.00,44266.00,42207.90,44230.20,206424.14,1704153599999,8897557996.5,2197331,107259.56,4626093916.7,0"


def _zip(csv_text: str, name: str = "x.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(name, csv_text)
    return buf.getvalue()


def _modern(rows: int = 1, first_ms: int = 1704067200000) -> bytes:
    """Archivo con cabecera (2022-06 en adelante)."""
    body = "\n".join(
        _ROW.replace("1704067200000", str(first_ms + i * 86_400_000), 1) for i in range(rows)
    )
    return _zip(",".join(KLINE_COLUMNS) + "\n" + body)


def _legacy(rows: int = 1, first_ms: int = 1577836800000) -> bytes:
    """Archivo SIN cabecera (2020)."""
    body = "\n".join(
        _ROW.replace("1704067200000", str(first_ms + i * 86_400_000), 1) for i in range(rows)
    )
    return _zip(body)


class FakeNet:
    """Red falsa: un dict url -> bytes. Cuenta accesos para probar idempotencia."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes | None:
        self.calls.append(url)
        if url.endswith(".CHECKSUM"):
            payload = self.files.get(url[: -len(".CHECKSUM")])
            if payload is None:
                return None
            return f"{hashlib.sha256(payload).hexdigest()}  file.zip\n".encode()
        return self.files.get(url)


# ── 1. Header por era: el bug que corrompe en silencio ───────────────────────────────

def test_reads_modern_files_without_eating_a_candle() -> None:
    frame = read_archive_csv(_modern(rows=3), KLINE_COLUMNS)
    assert len(frame) == 3, "la cabecera se conto como vela o se comio una"
    assert frame["open"].iloc[0] == 42314.0


def test_reads_legacy_files_without_injecting_a_text_row() -> None:
    frame = read_archive_csv(_legacy(rows=3), KLINE_COLUMNS)
    assert len(frame) == 3
    assert frame["open_time"].iloc[0] == 1577836800000


def test_both_eras_produce_the_same_shape() -> None:
    """El detector no puede cambiar el esquema segun la epoca del archivo."""
    modern = read_archive_csv(_modern(rows=2), KLINE_COLUMNS)
    legacy = read_archive_csv(_legacy(rows=2), KLINE_COLUMNS)
    assert list(modern.columns) == list(legacy.columns) == KLINE_COLUMNS
    assert len(modern) == len(legacy) == 2


# ── 2. Integridad y caché ────────────────────────────────────────────────────────────

def test_verifies_sha256_and_caches(tmp_path: Path) -> None:
    url = ("https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1d/"
           "BTCUSDT-1d-2024-01.zip")
    net = FakeNet({url: _modern()})
    archive = BinanceArchive(root=tmp_path, fetch=net)

    assert archive.fetch_file("klines", "BTCUSDT", "1d", "2024-01") is not None
    downloads = [c for c in net.calls if not c.endswith(".CHECKSUM")]
    assert downloads == [url]

    # Segunda vez: sale del caché, no toca la red. Esto es lo que hace reanudable
    # una descarga de cientos de archivos interrumpida a la mitad.
    archive.fetch_file("klines", "BTCUSDT", "1d", "2024-01")
    assert [c for c in net.calls if not c.endswith(".CHECKSUM")] == [url]


def test_rejects_a_corrupted_payload(tmp_path: Path) -> None:
    url = ("https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1d/"
           "BTCUSDT-1d-2024-01.zip")
    net = FakeNet({url: _modern()})
    net.files[url + "_"] = b""

    def corrupt(u: str) -> bytes | None:
        got = net(u)
        return b"basura" if got is not None and not u.endswith(".CHECKSUM") else got

    with pytest.raises(ValueError, match="checksum"):
        BinanceArchive(root=tmp_path, fetch=corrupt).fetch_file("klines", "BTCUSDT", "1d", "2024-01")
    assert not list(tmp_path.rglob("*.zip")), "un archivo corrupto no puede quedar cacheado"


def test_missing_file_is_information_not_an_error(tmp_path: Path) -> None:
    """404 = el simbolo no cotizaba ese mes. Normal para los 306 delistados."""
    archive = BinanceArchive(root=tmp_path, fetch=FakeNet({}))
    assert archive.fetch_file("klines", "DEADUSDT", "1d", "2021-05") is None


# ── 3. Panel continuo: mensuales + el hueco del mes en curso ─────────────────────────

def _url(period: str) -> str:
    span = "daily" if period.count("-") == 2 else "monthly"
    return (f"https://data.binance.vision/data/futures/um/{span}/klines/BTCUSDT/1d/"
            f"BTCUSDT-1d-{period}.zip")


def test_fills_the_current_month_gap_with_daily_files(tmp_path: Path) -> None:
    """El mensual de agosto no existe hasta septiembre: sin diarios, el panel llega tarde."""
    net = FakeNet({
        _url("2026-07"): _modern(rows=2, first_ms=1782864000000),
        _url("2026-08-01"): _modern(rows=1, first_ms=1785542400000),
        _url("2026-08-02"): _modern(rows=1, first_ms=1785628800000),
    })
    panel = BinanceArchive(root=tmp_path, fetch=net).load_klines(
        "BTCUSDT", start=date(2026, 7, 1), end=date(2026, 8, 2)
    )
    assert len(panel) == 4, "falto el tramo diario del mes en curso"
    assert panel["open_time"].is_monotonic_increasing


def test_deduplicates_overlapping_sources(tmp_path: Path) -> None:
    """Si un dia aparece en el mensual y en el diario, no puede contarse dos veces."""
    same = _modern(rows=1, first_ms=1785542400000)
    net = FakeNet({_url("2026-08"): same, _url("2026-08-01"): same})
    panel = BinanceArchive(root=tmp_path, fetch=net).load_klines(
        "BTCUSDT", start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    assert len(panel) == 1


def test_delisted_symbol_returns_empty_with_the_right_columns(tmp_path: Path) -> None:
    panel = BinanceArchive(root=tmp_path, fetch=FakeNet({})).load_klines(
        "DEADUSDT", start=date(2021, 1, 1), end=date(2021, 1, 3)
    )
    assert panel.empty and list(panel.columns) == KLINE_COLUMNS


def test_funding_keeps_the_interval_column(tmp_path: Path) -> None:
    """`funding_interval_hours` NO es la constante 8: se lee del dato."""
    url = ("https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/"
           "BTCUSDT-fundingRate-2024-01.zip")
    csv = ",".join(FUNDING_COLUMNS) + "\n1704067200000,8,0.00037409\n1704096000000,4,0.00027213"
    net = FakeNet({url: _zip(csv)})
    funding = BinanceArchive(root=tmp_path, fetch=net).load_funding(
        "BTCUSDT", start=date(2024, 1, 1), end=date(2024, 1, 31)
    )
    assert list(funding["funding_interval_hours"]) == [8.0, 4.0]


# ── 4. Utilidades de calendario y ubicación del caché ────────────────────────────────

def test_month_and_day_ranges_are_inclusive_and_cross_year() -> None:
    assert list(months_between(date(2020, 11, 5), date(2021, 2, 2))) == [
        "2020-11", "2020-12", "2021-01", "2021-02"]
    assert list(days_between(date(2021, 12, 30), date(2022, 1, 1))) == [
        "2021-12-30", "2021-12-31", "2022-01-01"]


def test_cache_root_is_overridable_and_defaults_outside_icloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAINEXT_FUTURES_DATA_DIR", "/tmp/panel")
    assert default_cache_root() == Path("/tmp/panel")
    monkeypatch.delenv("KAINEXT_FUTURES_DATA_DIR")
    root = default_cache_root()
    assert "Mobile Documents" not in str(root), "el panel NO puede caer en iCloud"


# ── 5. Recorte al rango pedido: los mensuales traen el mes ENTERO ────────────────────

def test_panel_never_returns_candles_past_the_requested_end(tmp_path: Path) -> None:
    """Pedir hasta el 5 de marzo no puede devolver marzo entero.

    Los archivos vienen por mes completo. Sin recorte, un backtest recibe velas
    POSTERIORES a su ventana — lookahead, aunque nadie las mire a proposito.
    Bug real: se detecto corriendo la capa contra el archivo real de Binance.
    """
    march = _modern(rows=31, first_ms=1583020800000)  # 2020-03-01 .. 2020-03-31
    net = FakeNet({_url("2020-03"): march})
    panel = BinanceArchive(root=tmp_path, fetch=net).load_klines(
        "BTCUSDT", start=date(2020, 3, 1), end=date(2020, 3, 5)
    )
    assert len(panel) == 5, f"devolvio {len(panel)} velas para un rango de 5 dias"
    assert int(panel["open_time"].iloc[-1]) == 1583020800000 + 4 * 86_400_000


def test_panel_never_returns_candles_before_the_requested_start(tmp_path: Path) -> None:
    march = _modern(rows=31, first_ms=1583020800000)
    net = FakeNet({_url("2020-03"): march})
    panel = BinanceArchive(root=tmp_path, fetch=net).load_klines(
        "BTCUSDT", start=date(2020, 3, 20), end=date(2020, 3, 31)
    )
    assert len(panel) == 12
    assert int(panel["open_time"].iloc[0]) == 1583020800000 + 19 * 86_400_000


def test_funding_is_clipped_too(tmp_path: Path) -> None:
    url = ("https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/"
           "BTCUSDT-fundingRate-2024-01.zip")
    rows = "\n".join(f"{1704067200000 + i * 28800000},8,0.0001" for i in range(93))
    net = FakeNet({url: _zip(",".join(FUNDING_COLUMNS) + "\n" + rows)})
    funding = BinanceArchive(root=tmp_path, fetch=net).load_funding(
        "BTCUSDT", start=date(2024, 1, 1), end=date(2024, 1, 2)
    )
    assert len(funding) == 6, "2 dias x 3 eventos de 8h"
