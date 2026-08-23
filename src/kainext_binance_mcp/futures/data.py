"""Panel histórico de futuros USDⓈ-M desde los archivos públicos de Binance.

Por qué archivos y no REST: el universo son ~986 símbolos y la REST devuelve 1000 velas
por llamada. Bajar cinco años de historia por REST es inviable; los archivos mensuales
pesan ~120 MB para todo el universo en 1d.

Tres decisiones que no son obvias y que vienen de mirar los archivos reales:

1. **El header cambió de era.** Los archivos de 2020 vienen SIN cabecera; los de 2022 en
   adelante SÍ. Asumir cualquiera de las dos corrompe en silencio: se pierde la primera
   vela de cada mes antiguo, o entra una fila de texto en los modernos. Se detecta.
2. **El mes en curso no está en los mensuales.** Binance publica el mensual recién el
   primer lunes del mes siguiente, así que hay hasta ~5 semanas de hueco que hay que
   rellenar con los archivos diarios. Sin esto el panel llega atrasado y nadie lo nota.
3. **La vela de hoy no se usa.** Está incompleta hasta el cierre UTC, y una vela parcial
   en un ranking de momentum es lookahead disfrazado. El panel termina ayer, a propósito.
"""
from __future__ import annotations

import hashlib
import io
import os
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data.binance.vision/data/futures/um"

# Las 12 columnas del CSV de klines, en orden. `ignore` existe en el formato de Binance.
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
FUNDING_COLUMNS = ["calc_time", "funding_interval_hours", "last_funding_rate"]

# El primer mes con datos de futuros USDⓈ-M.
HISTORY_START = date(2020, 1, 1)

Fetcher = Callable[[str], bytes | None]
"""Descarga una URL. Devuelve None si el archivo no existe (404); levanta si falla de otro modo."""


def default_cache_root() -> Path:
    """Dónde vive el panel. FUERA de iCloud a propósito.

    El home del operador sincroniza el vault de Obsidian por iCloud; dejar ahí cientos de
    MB de datos de mercado sincronizando es un problema real, no teórico.
    """
    env = os.environ.get("KAINEXT_FUTURES_DATA_DIR")
    return Path(env) if env else Path.home() / ".cache" / "kainext-futures"


def _http_fetch(url: str) -> bytes | None:
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def _epoch_ms(day: date) -> int:
    """Medianoche UTC de `day` en milisegundos (el `open_time` de su vela diaria)."""
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _clip(frame: pd.DataFrame, column: str, start: date, end: date) -> pd.DataFrame:
    """Recorta al rango pedido, inclusive en ambos extremos.

    Imprescindible: los archivos vienen por mes completo, así que pedir hasta el 5 de
    marzo devolvía marzo entero. Un backtest que recibe velas POSTERIORES a su ventana
    es lookahead, aunque nadie las mire a propósito.
    """
    lo, hi = _epoch_ms(start), _epoch_ms(end + timedelta(days=1))
    return frame[(frame[column] >= lo) & (frame[column] < hi)]


def months_between(start: date, end: date) -> Iterator[str]:
    """Etiquetas `YYYY-MM` desde `start` hasta el mes de `end`, inclusive."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year:04d}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def days_between(start: date, end: date) -> Iterator[str]:
    """Etiquetas `YYYY-MM-DD` desde `start` hasta `end`, inclusive."""
    day = start
    while day <= end:
        yield day.isoformat()
        day += timedelta(days=1)


def read_archive_csv(payload: bytes, columns: list[str]) -> pd.DataFrame:
    """Descomprime un archivo de Binance y lo parsea detectando si trae cabecera.

    La detección es el punto: los archivos viejos no la traen y los nuevos sí (verificado
    contra 2020-01 vs 2022-06+). `header=0` fijo se come la primera vela de cada mes
    antiguo; `header=None` fijo mete una fila de texto en los modernos.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        raw = archive.read(name)
    first_line = raw.split(b"\n", 1)[0].decode("utf-8", "replace")
    has_header = first_line.split(",")[0].strip().strip('"') == columns[0]
    frame = pd.read_csv(
        io.BytesIO(raw), header=0 if has_header else None, names=columns, dtype="float64"
    )
    return frame


class BinanceArchive:
    """Descarga verificada y cacheada de los archivos públicos de futuros.

    Idempotente y reanudable: un archivo ya cacheado y con checksum válido no se vuelve a
    bajar, así que una descarga interrumpida se retoma corriendo lo mismo otra vez.
    """

    def __init__(self, root: Path | None = None, fetch: Fetcher | None = None) -> None:
        self.root = root or default_cache_root()
        self._fetch = fetch or _http_fetch

    # ── rutas ────────────────────────────────────────────────────────────────────────
    def _url(self, kind: str, symbol: str, interval: str | None, period: str) -> str:
        span = "daily" if period.count("-") == 2 else "monthly"
        if kind == "klines":
            assert interval is not None
            return f"{BASE_URL}/{span}/klines/{symbol}/{interval}/{symbol}-{interval}-{period}.zip"
        return f"{BASE_URL}/{span}/fundingRate/{symbol}/{symbol}-fundingRate-{period}.zip"

    def _cache_path(self, url: str) -> Path:
        return self.root / url[len(BASE_URL) + 1:]

    # ── descarga ─────────────────────────────────────────────────────────────────────
    def fetch_file(self, kind: str, symbol: str, interval: str | None, period: str) -> bytes | None:
        """Devuelve el zip, del caché o de la red. `None` si Binance no lo publica.

        Un 404 es información legítima, no un error: un símbolo no cotizaba ese mes, o el
        mensual del mes en curso todavía no existe.
        """
        url = self._url(kind, symbol, interval, period)
        path = self._cache_path(url)
        if path.exists():
            return path.read_bytes()

        payload = self._fetch(url)
        if payload is None:
            return None
        self._verify(url, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Escritura atómica: un Ctrl-C a mitad no deja un zip truncado en el caché que
        # el próximo run daría por bueno.
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.replace(path)
        return payload

    def _verify(self, url: str, payload: bytes) -> None:
        """Coteja contra el `.CHECKSUM` (SHA256) que Binance publica junto a cada zip."""
        checksum = self._fetch(url + ".CHECKSUM")
        if checksum is None:
            return  # Binance no publicó checksum para este archivo: no hay con qué comparar.
        expected = checksum.decode("utf-8", "replace").split()[0]
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise ValueError(f"checksum SHA256 no coincide para {url}: {actual} != {expected}")

    # ── panel ────────────────────────────────────────────────────────────────────────
    def load_klines(
        self, symbol: str, interval: str = "1d", *,
        start: date = HISTORY_START, end: date | None = None,
    ) -> pd.DataFrame:
        """Serie OHLCV continua de `symbol`, sin hueco hasta ayer.

        Combina los mensuales (histórico) con los diarios (el mes en curso, que el
        mensual todavía no cierra). Devuelve un DataFrame vacío si el símbolo no tiene
        datos en el rango — que es lo normal para los 306 símbolos ya delistados.
        """
        end = end or date.today() - timedelta(days=1)
        frames: list[pd.DataFrame] = []
        covered_until: date | None = None

        for period in months_between(start, end):
            payload = self.fetch_file("klines", symbol, interval, period)
            if payload is None:
                continue
            frames.append(read_archive_csv(payload, KLINE_COLUMNS))
            year, month = (int(x) for x in period.split("-"))
            last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
            covered_until = min(last, end)

        # Hueco: desde el día siguiente al último mensual disponible hasta `end`.
        gap_start = (covered_until + timedelta(days=1)) if covered_until else start
        for day in days_between(gap_start, end):
            payload = self.fetch_file("klines", symbol, interval, day)
            if payload is not None:
                frames.append(read_archive_csv(payload, KLINE_COLUMNS))

        if not frames:
            return pd.DataFrame(columns=KLINE_COLUMNS)
        panel = pd.concat(frames, ignore_index=True)
        panel = panel.drop_duplicates(subset="open_time").sort_values("open_time")
        return _clip(panel, "open_time", start, end).reset_index(drop=True)

    def load_funding(
        self, symbol: str, *, start: date = HISTORY_START, end: date | None = None,
    ) -> pd.DataFrame:
        """Historial de funding de `symbol`, conservando `funding_interval_hours`.

        El intervalo es un campo del dato, no la constante 8 h que todo el mundo asume:
        Binance lo modela como variable y el accrual tiene que respetarlo.
        """
        end = end or date.today() - timedelta(days=1)
        frames = [
            read_archive_csv(payload, FUNDING_COLUMNS)
            for period in months_between(start, end)
            if (payload := self.fetch_file("funding", symbol, None, period)) is not None
        ]
        if not frames:
            return pd.DataFrame(columns=FUNDING_COLUMNS)
        funding = pd.concat(frames, ignore_index=True)
        funding = funding.drop_duplicates(subset="calc_time").sort_values("calc_time")
        return _clip(funding, "calc_time", start, end).reset_index(drop=True)
