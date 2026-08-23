"""Universo point-in-time de perpetuos USDⓈ-M.

El sesgo de supervivencia es la forma más fácil de producir un backtest de momentum
espectacular y falso. Hoy cotizan 527 perpetuos USDT, pero el archivo tiene 986 símbolos:
**306 perpetuos USDT ya delistados**. Rankear solo los que siguen vivos es preguntarle al
pasado usando la respuesta del futuro.

La pertenencia se deriva **del dato**, no de un registro aparte: un símbolo pertenece al
universo en `t` si tiene una vela cerrada en `t`. Si dejó de publicar velas, se delistó, y
la cartera lo cierra al último precio disponible en vez de hacerlo desaparecer.

Los símbolos con multiplicador (`1000PEPE`, `1000000BOB`, …) se tratan como instrumentos
distintos y **nunca** se encadenan con su versión previa: un relisteo con otro
multiplicador produce un salto de precio de ×1000 que aparecería como un retorno de
+99.900% y dominaría cualquier ranking de momentum. Trece de los 527 vivos llevan
multiplicador, así que no es un caso hipotético.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from urllib.parse import quote

import pandas as pd
import requests

from .data import BinanceArchive

_LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_PREFIX = "data/futures/um/monthly/klines/"

# Nombres con multiplicador de denominación. No se encadenan jamás con su base.
_MULTIPLIER = re.compile(r"^(1000+|1M)[A-Z0-9]+USDT$")

XmlFetcher = Callable[[str], str]


def _http_get_text(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def list_archive_symbols(fetch: XmlFetcher | None = None) -> list[str]:
    """Todos los símbolos con klines en el archivo — **incluidos los delistados**.

    Es la fuente de la que sale el universo sin sesgo de supervivencia: `exchangeInfo`
    solo conoce lo que cotiza hoy.
    """
    fetch = fetch or _http_get_text
    symbols: list[str] = []
    token = ""
    while True:
        url = f"{_LIST_URL}?list-type=2&delimiter=/&prefix={_PREFIX}&max-keys=1000{token}"
        root = ET.fromstring(fetch(url))
        for node in root.findall(f"{_NS}CommonPrefixes/{_NS}Prefix"):
            if node.text:
                symbols.append(node.text[len(_PREFIX):].rstrip("/"))
        nxt = root.findtext(f"{_NS}NextContinuationToken")
        if not nxt:
            return sorted(set(symbols))
        token = f"&continuation-token={quote(nxt, safe='')}"


def usdt_perpetuals(symbols: list[str]) -> list[str]:
    """Solo perpetuos con cotización en USDT.

    El archivo mezcla monedas de cotización (USDT, USDC, USD1, BTC). Un universo que las
    mezcla compara retornos denominados en cosas distintas.
    """
    return [s for s in symbols if s.endswith("USDT")]


def has_denomination_multiplier(symbol: str) -> bool:
    """`1000PEPEUSDT` y compañía: instrumento propio, nunca continuación de su base."""
    return bool(_MULTIPLIER.match(symbol))


class Universe:
    """Panel ancho (fechas × símbolos) con la pertenencia derivada del propio dato."""

    def __init__(self, archive: BinanceArchive, symbols: list[str]) -> None:
        self.archive = archive
        self.symbols = symbols

    def load_panels(
        self, *, start: date, end: date | None = None, interval: str = "1d",
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Devuelve `(close, quote_volume)` indexados por `open_time`.

        Un `NaN` significa "no cotizaba ese día": es la ausencia la que codifica el alta y
        la baja del símbolo, sin necesidad de un registro de listings aparte.
        """
        closes: dict[str, pd.Series] = {}
        volumes: dict[str, pd.Series] = {}
        for symbol in self.symbols:
            frame = self.archive.load_klines(symbol, interval, start=start, end=end)
            if frame.empty:
                continue
            indexed = frame.set_index("open_time")
            closes[symbol] = indexed["close"]
            volumes[symbol] = indexed["quote_volume"]
        if not closes:
            empty = pd.DataFrame()
            return empty, empty
        return pd.DataFrame(closes).sort_index(), pd.DataFrame(volumes).sort_index()

    @staticmethod
    def members_at(
        closes: pd.DataFrame,
        volumes: pd.DataFrame,
        when: int,
        *,
        min_history: int = 90,
        min_adv_usd: float = 1_000_000.0,
        adv_window: int = 30,
    ) -> list[str]:
        """Qué símbolos son elegibles en `when`, usando SOLO información hasta `when`.

        Tres condiciones, todas causales: que cotice ese día, que tenga historia
        suficiente para calcular la señal, y que mueva volumen real. El filtro de
        liquidez es el que evita que el decil ganador se llene de símbolos muertos
        cuyo "retorno" es ruido de un libro vacío.
        """
        if closes.empty or when not in closes.index:
            return []
        upto = closes.loc[:when]
        history = upto.notna().sum()
        adv = volumes.loc[:when].tail(adv_window).mean()
        alive = upto.loc[when].notna()
        eligible = alive & (history >= min_history) & (adv >= min_adv_usd)
        return sorted(eligible.index[eligible].tolist())
