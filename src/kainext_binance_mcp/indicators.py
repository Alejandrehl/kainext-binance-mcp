"""Indicadores técnicos puros sobre ``pandas.Series`` (spec §4, E2/E3).

Cálculo determinista en pandas/numpy (sin TA-Lib ni pandas-ta) para poder testear
contra golden values. Todas las funciones son puras: no muten su entrada y devuelven
``pandas.Series`` (o tupla de ellas) de ``float`` — los indicadores son analíticos,
no montos de orden (E3).

Definiciones (spec §4):
- EMA(n): alpha = 2/(n+1), recursión sembrada en el primer valor (``adjust=False``).
- RSI(n=14): Wilder; RS = avgGain/avgLoss (suavizado de Wilder); RSI = 100 - 100/(1+RS).
- MACD(12,26,9): macd = EMA12 - EMA26; signal = EMA9(macd); hist = macd - signal.
- Bollinger(20,2): SMA20 ± k·std20 (std poblacional, ddof=0; std=0 => banda colapsa).
- ATR(14): Wilder sobre True Range = max(high-low, |high-prevClose|, |low-prevClose|).
"""
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, n: int) -> pd.Series:
    """EMA con alpha = 2/(n+1), sembrada en el primer valor (recursión clásica)."""
    if n <= 0:
        raise ValueError("n must be > 0")
    return series.astype("float64").ewm(span=n, adjust=False).mean()


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    """RSI de Wilder. Devuelve valores en [0, 100]; NaN en los primeros n puntos.

    Casos límite (deterministas):
    - sólo ganancias (avgLoss=0) => RS=inf => RSI=100.
    - sólo pérdidas (avgGain=0) => RS=0 => RSI=0.
    """
    if n <= 0:
        raise ValueError("n must be > 0")
    s = series.astype("float64")
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Suavizado de Wilder: EMA con alpha = 1/n (equivalente a ewm(alpha=1/n)).
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    # avgLoss=0 => RS=inf => out=100. avgGain=0 & avgLoss=0 (serie plana) => 0/0=NaN -> 50 neutral.
    out = out.where(avg_loss != 0.0, 100.0)
    flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    out = out.where(~flat, 50.0)
    # Restaurar NaN del periodo de calentamiento (donde no hay promedio aún).
    out = out.where(avg_gain.notna(), other=float("nan"))
    return out


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD/signal/hist. Devuelve (macd_line, signal_line, histogram)."""
    s = series.astype("float64")
    macd_line = ema(s, fast) - ema(s, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(
    series: pd.Series, n: int = 20, k: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bandas de Bollinger: (upper, mid, lower) = SMA(n) ± k·std(n).

    std poblacional (ddof=0): para una serie constante std=0 y las bandas colapsan al precio.
    """
    if n <= 0:
        raise ValueError("n must be > 0")
    s = series.astype("float64")
    mid = s.rolling(window=n).mean()
    std = s.rolling(window=n).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """ATR de Wilder sobre el True Range = max(high-low, |high-prevClose|, |low-prevClose|)."""
    if n <= 0:
        raise ValueError("n must be > 0")
    h = high.astype("float64")
    low_ = low.astype("float64")
    c = close.astype("float64")
    prev_close = c.shift(1)
    tr = pd.concat(
        [(h - low_), (h - prev_close).abs(), (low_ - prev_close).abs()], axis=1
    ).max(axis=1)
    # Suavizado de Wilder (alpha = 1/n).
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
