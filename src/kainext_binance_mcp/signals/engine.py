"""Motor de señales transparente y determinista (spec §5). PURO — sin red.

``generate_signal`` recibe indicadores YA calculados (capa 2) + un sentiment crudo
(capa 3) + ATR, y compone una ``Signal``:

1. Cada factor produce un ``value`` normalizado en [-1, +1] (lo que "opina") y una
   ``contribution = value · weight`` (lo que efectivamente empuja al score). Todo se
   expone en ``Signal.factors`` — sin caja negra (spec S3).
2. ``score = clip(Σ contributions, -1, +1)``.
3. ``direction`` por umbral (spec S5): ``long`` si score ≥ +threshold, ``avoid`` si
   score ≤ −threshold, ``hold`` en la zona neutra.
4. Niveles de riesgo por ATR (spec S4): para ``long`` el stop va abajo y el target arriba;
   para ``avoid`` se **invierten** (riesgo al alza si tenés/querés salir de lo que tenés);
   para ``hold`` no hay niveles (``None``).

Pesos default (suma 1.0, tuneables — spec S2): trend .30, momentum .20, macd .20,
bollinger .15, sentiment .15. Con todos los factores saturados en la misma dirección el
score llega a ±1 antes del clip.

Mapeos de factor (todos acotados a [-1, +1], deterministas, verificables a mano):
- **trend:** signo de (ema_fast − ema_slow) ∈ {-1, 0, +1}.
- **momentum (RSI):** lineal (50 − rsi)/20 → rsi 30 ⇒ +1 (sobreventa), rsi 70 ⇒ −1
  (sobrecompra), rsi 50 ⇒ 0; recortado a [-1, +1].
- **macd:** signo del histograma ∈ {-1, 0, +1}.
- **bollinger:** posición %B (0 = banda inferior, 1 = superior): value = 1 − 2·bb_pos,
  recortado a [-1, +1] (cerca de la inferior ⇒ +, posible rebote; superior ⇒ −).
- **sentiment:** el score crudo de capa 3, recortado a [-1, +1].
"""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from kainext_binance_mcp.models import Signal, SignalDirection, SignalFactor

# Pesos default documentados (spec S2). Suma 1.0.
DEFAULT_WEIGHTS: dict[str, float] = {
    "trend": 0.30,
    "momentum": 0.20,
    "macd": 0.20,
    "bollinger": 0.15,
    "sentiment": 0.15,
}

# Umbral de dirección (spec S5): |score| ≥ threshold define long/avoid; debajo, hold.
DEFAULT_THRESHOLD: float = 0.15
# Riesgo (spec S4): stop = k·ATR del entry; target = R·k·ATR.
DEFAULT_ATR_MULT: float = 1.5
DEFAULT_RR: float = 2.0

# RSI: punto neutro y media-amplitud del mapeo lineal (30↔+1, 70↔-1).
_RSI_NEUTRAL = 50.0
_RSI_HALF_SPAN = 20.0

_DISCLAIMER = (
    "PROPUESTA, no predicción: combinación heurística y determinista de indicadores "
    "técnicos (capa 2) + sentiment CRUDO (capa 3) + ATR. No garantiza nada, no decide "
    "tamaño de posición y NO ejecuta — la decisión y la orden son tuyas (gate de capa 1). "
    "Validá la regla con backtest antes de confiar en ella."
)


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _trend_value(ema_fast: float, ema_slow: float) -> tuple[float, str]:
    diff = ema_fast - ema_slow
    if diff > 0:
        return 1.0, "EMA rápida sobre la lenta: tendencia alcista."
    if diff < 0:
        return -1.0, "EMA rápida bajo la lenta: tendencia bajista."
    return 0.0, "EMA rápida y lenta iguales: sin tendencia clara."


def _momentum_value(rsi: float) -> tuple[float, str]:
    value = _clip((_RSI_NEUTRAL - rsi) / _RSI_HALF_SPAN)
    # La nota describe el lean real (signo/magnitud de value) para nunca contradecir la
    # contribución: <30/>70 son los extremos clásicos; en el medio, el sesgo es proporcional.
    if rsi < 30.0:
        note = f"RSI {rsi:.1f} en sobreventa: posible rebote (momentum a favor)."
    elif rsi > 70.0:
        note = f"RSI {rsi:.1f} en sobrecompra: riesgo de corrección (momentum en contra)."
    elif rsi < 45.0:
        note = f"RSI {rsi:.1f} bajo el punto medio: leve sesgo a favor."
    elif rsi > 55.0:
        note = f"RSI {rsi:.1f} sobre el punto medio: leve sesgo en contra."
    else:
        note = f"RSI {rsi:.1f} en zona neutra: momentum ~neutro."
    return value, note


def _macd_value(macd_hist: float) -> tuple[float, str]:
    if macd_hist > 0:
        return 1.0, "Histograma MACD positivo: impulso alcista."
    if macd_hist < 0:
        return -1.0, "Histograma MACD negativo: impulso bajista."
    return 0.0, "Histograma MACD en cero: impulso neutro."


def _bollinger_value(bb_pos: float) -> tuple[float, str]:
    value = _clip(1.0 - 2.0 * bb_pos)
    if bb_pos <= 0.25:
        note = "Precio cerca de la banda inferior de Bollinger: posible rebote."
    elif bb_pos >= 0.75:
        note = "Precio cerca de la banda superior de Bollinger: posible reversión a la baja."
    else:
        note = "Precio en torno a la media de Bollinger: neutro."
    return value, note


def _sentiment_value(sentiment: float) -> tuple[float, str]:
    value = _clip(sentiment)
    note = f"Sentiment crudo de noticias = {value:+.2f} (capa 3; señal cruda, no análisis)."
    return value, note


def _factor(name: str, value: float, weight: float, note: str) -> SignalFactor:
    return SignalFactor(
        name=name,
        value=value,
        weight=weight,
        contribution=value * weight,
        note=note,
    )


def _direction(score: float, threshold: float) -> SignalDirection:
    if score >= threshold:
        return "long"
    if score <= -threshold:
        return "avoid"
    return "hold"


def _levels(
    direction: SignalDirection, price: Decimal, atr: float, atr_mult: float, rr: float
) -> tuple[Decimal | None, Decimal | None]:
    """Stop/target por ATR (spec S4).

    - ``long``: stop = price − atr_mult·ATR (abajo); target = price + rr·atr_mult·ATR (arriba).
    - ``avoid``: se invierten — stop = price + atr_mult·ATR (arriba); target = price −
      rr·atr_mult·ATR (abajo). Cubre el caso de proteger/salir de una posición existente.
    - ``hold``: sin niveles (None).
    """
    risk = Decimal(str(atr)) * Decimal(str(atr_mult))
    reward = risk * Decimal(str(rr))
    if direction == "long":
        return price - risk, price + reward
    if direction == "avoid":
        return price + risk, price - reward
    return None, None


def generate_signal(
    *,
    symbol: str,
    interval: str,
    price: Decimal,
    ema_fast: float,
    ema_slow: float,
    rsi: float,
    macd_hist: float,
    bb_pos: float,
    sentiment: float,
    atr: float,
    weights: Mapping[str, float] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    atr_mult: float = DEFAULT_ATR_MULT,
    rr: float = DEFAULT_RR,
    as_of: int,
) -> Signal:
    """Compone una ``Signal`` transparente a partir de indicadores + sentiment + ATR.

    PURO: no pega a Binance ni lee feeds — recibe los valores ya calculados (la tool de
    ``tools/signals.py`` arma esos inputs desde capa 2/3). Cada factor expone su value,
    weight y contribution; el score es la suma acotada; la dirección sale del umbral y los
    niveles de riesgo del ATR. Siempre puebla ``factors`` y ``disclaimer`` (spec S3/S6).
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights is not None:
        w.update(weights)

    trend_v, trend_note = _trend_value(ema_fast, ema_slow)
    mom_v, mom_note = _momentum_value(rsi)
    macd_v, macd_note = _macd_value(macd_hist)
    boll_v, boll_note = _bollinger_value(bb_pos)
    sent_v, sent_note = _sentiment_value(sentiment)

    factors = [
        _factor("trend", trend_v, w["trend"], trend_note),
        _factor("momentum", mom_v, w["momentum"], mom_note),
        _factor("macd", macd_v, w["macd"], macd_note),
        _factor("bollinger", boll_v, w["bollinger"], boll_note),
        _factor("sentiment", sent_v, w["sentiment"], sent_note),
    ]

    score = _clip(sum(f.contribution for f in factors))
    direction = _direction(score, threshold)
    stop, target = _levels(direction, price, atr, atr_mult, rr)

    return Signal(
        symbol=symbol,
        interval=interval,
        direction=direction,
        score=score,
        factors=factors,
        price=price,
        suggested_stop=stop,
        suggested_target=target,
        atr=atr,
        disclaimer=_DISCLAIMER,
        as_of=as_of,
    )
