"""Modelos Pydantic de entrada/salida y el CanonicalOrder (spec §3.3/§3.4)."""
from __future__ import annotations
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, model_validator

# Único formato de symbol aceptado en TODO el sistema (tools read incluidas; en
# CanonicalOrder además es el trust boundary hacia AppleScript).
SYMBOL_PATTERN = r"^[A-Z0-9]{2,20}$"

# Estados terminales de una orden: proponer/ejecutar una cancelación sobre ellos es error.
# Único home (lo comparten tools/write.py y el confirmador).
NOT_CANCELABLE: frozenset[str] = frozenset({"FILLED", "CANCELED", "EXPIRED"})

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT"]
Env = Literal["testnet", "mainnet"]
TimeInForce = Literal["GTC", "IOC", "FOK"]


class CanonicalOrder(BaseModel):
    """Lo ÚNICO que viaja por IPC al confirmador. Sin texto, sin id, sin hash."""
    model_config = {"frozen": True}
    # Trust boundary: symbol es el único texto controlado por el modelo que llega a un
    # intérprete (AppleScript, dialog.py). El pattern lo cierra acá, en el modelo canónico.
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    side: Side
    type: OrderType
    quantity: Decimal | None = None
    quote_quantity: Decimal | None = None
    price: Decimal | None = None
    time_in_force: TimeInForce | None = None
    env: Env

    @model_validator(mode="after")
    def _check(self) -> "CanonicalOrder":
        if self.type == "LIMIT":
            if self.price is None:
                raise ValueError("LIMIT requires price")
            if self.time_in_force is None:
                raise ValueError("LIMIT requires time_in_force (the tool defaults to GTC)")
            if self.quote_quantity is not None:
                raise ValueError("quote_quantity only applies to MARKET orders")
            if self.quantity is None:
                raise ValueError("LIMIT requires quantity")
        if self.type == "MARKET":
            if self.price is not None:
                raise ValueError("MARKET does not accept price")
            if self.time_in_force is not None:
                raise ValueError("MARKET does not accept time_in_force")
        if (self.quantity is None) == (self.quote_quantity is None):
            raise ValueError("exactly one of quantity / quote_quantity is required")
        for v in (self.quantity, self.quote_quantity, self.price):
            if v is not None and v <= 0:
                raise ValueError("amounts must be > 0")
        return self


class KeyPermissions(BaseModel):
    enable_spot_and_margin_trading: bool
    enable_withdrawals: bool
    permits_universal_transfer: bool
    enable_internal_transfer: bool
    enable_margin: bool
    enable_futures: bool
    enable_portfolio_margin_trading: bool
    ip_restrict: bool


class OrderPreview(BaseModel):
    effective_qty: Decimal | None
    price: Decimal | None
    est_notional: Decimal | None
    est_commission: Decimal | None
    env: Env
    warnings: list[str] = []
    feasible: bool
    reason: str | None = None


class OrderProposal(BaseModel):
    intent_id: str | None = None
    expires_at: int | None = None
    server_estimate: OrderPreview | None = None  # NO autoritativa; el diálogo lo renderiza el confirmador
    error: ToolError | None = None  # poblado cuando la propuesta no procede (ej. orden ya no cancelable)


class Fill(BaseModel):
    price: Decimal
    qty: Decimal
    commission: Decimal
    commission_asset: str


class OrderResult(BaseModel):
    order_id: int
    client_order_id: str
    status: str
    executed_qty: Decimal
    cummulative_quote_qty: Decimal
    fills: list[Fill] = []
    env: Env


class CancelResult(BaseModel):
    """Resultado de una cancelación (spec §3.3). Distinto de OrderResult: una cancelación
    no tiene fills ni qty ejecutada propia, sólo el desenlace."""
    order_id: int
    status: Literal["CANCELED", "NOT_CANCELABLE"]
    detail: str = ""
    env: Env


class ToolError(BaseModel):
    error: Literal[True] = True
    code: int | str
    message: str


class OrderStatus(BaseModel):
    intent_id: str
    state: Literal["pending", "executed", "rejected", "expired", "failed", "unknown"]
    # result es OrderResult (órdenes) o CancelResult (cancelaciones); None mientras no haya
    # desenlace. Union "smart" de Pydantic v2 elige por forma del payload.
    result: OrderResult | CancelResult | None = None
    error: ToolError | None = None


class AssetBalance(BaseModel):
    asset: str
    free: Decimal
    locked: Decimal


class OpenOrder(BaseModel):
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    type: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    time_in_force: str
    time: int


class PriceTicker(BaseModel):
    symbol: str
    price: Decimal


class AccountInfo(BaseModel):
    can_trade: bool
    commission_rates: dict[str, Decimal]
    account_type: str
    key_permissions: "KeyPermissions | None" = None


# --- Capa 2: market data + indicadores (read-only). OHLCV en Decimal (E3); indicadores en float. ---

class Kline(BaseModel):
    """Vela OHLCV. OHLCV en Decimal por consistencia con capa 1 (E3)."""
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: int


class Ticker24h(BaseModel):
    """Stats rolling 24h de un par."""
    symbol: str
    price_change_pct: Decimal
    high: Decimal
    low: Decimal
    volume: Decimal
    last: Decimal


class IndicatorResult(BaseModel):
    """Series de indicadores calculados sobre las klines. Valores en float (analíticos, E3).

    ``indicators`` mapea nombre -> serie alineada con las velas; ``None`` en el periodo de
    calentamiento de cada indicador. ``as_of`` = close_time de la última vela usada.
    """
    symbol: str
    interval: str
    indicators: dict[str, list[float | None]]
    as_of: int


class BacktestResult(BaseModel):
    """Resultado de un backtest liviano (E5). Métricas en float; honesto y sin promesas."""
    symbol: str
    interval: str
    strategy: str
    total_return_pct: float
    buy_hold_return_pct: float
    n_trades: int
    win_rate: float
    max_drawdown_pct: float
    disclaimer: str


# --- Capa 3: noticias + sentiment (read-only). Sentiment en float (señal cruda, spec §4). ---

class NewsItem(BaseModel):
    """Un ítem de noticia normalizado desde un feed RSS (spec §4).

    ``published`` es epoch en segundos. ``sentiment`` es el score crudo del item en
    [-1, +1] (léxico determinista, ver ``news.sentiment``). ``assets`` son los símbolos
    canónicos detectados en título+resumen.
    """
    title: str
    summary: str
    source: str
    published: int
    url: str
    assets: list[str] = []
    sentiment: float = 0.0


class SentimentResult(BaseModel):
    """Agregado de sentiment crudo por activo sobre una ventana (spec §4).

    ``score`` = promedio del sentiment de los ``n_items`` del activo en la ventana.
    ``sample`` son items representativos. ``disclaimer`` es obligatorio y explícito:
    señal cruda, no es análisis; el juicio fino lo hace Claude leyendo los items.
    """
    asset: str
    window_hours: int
    score: float
    n_items: int
    sample: list[NewsItem] = []
    disclaimer: str


# --- Capa 4: motor de señales (read-only, PROPONE). Score y factores en float (analíticos);
# precio y niveles de riesgo en Decimal (E3, consistencia con capa 1). ---

SignalDirection = Literal["long", "hold", "avoid"]


class SignalFactor(BaseModel):
    """Un factor de la señal compuesta y su aporte transparente al score (spec §4/§5).

    ``value`` es el valor normalizado del factor en [-1, +1] (lo que el factor "opina");
    ``weight`` su peso en la mezcla; ``contribution`` = value·weight (lo que efectivamente
    empujó al score). ``note`` explica en lenguaje claro qué se midió. Sin caja negra (S3).
    """
    name: str
    value: float
    weight: float
    contribution: float
    note: str


class Signal(BaseModel):
    """Señal compuesta transparente para un par (spec §4/§5). PROPONE; nunca ejecuta (S1).

    ``score`` ∈ [-1, +1] = suma acotada de las ``contribution`` de cada ``factors``.
    ``direction`` por umbral (S5). ``price`` es el precio actual (entry sugerido) y
    ``suggested_stop``/``suggested_target`` derivan de ATR (S4): poblados para long/avoid,
    ``None`` para hold (zona neutra). ``disclaimer`` obligatorio (S6): no es predicción.
    """
    symbol: str
    interval: str
    direction: SignalDirection
    score: float
    factors: list[SignalFactor]
    price: Decimal
    suggested_stop: Decimal | None = None
    suggested_target: Decimal | None = None
    atr: float
    disclaimer: str
    as_of: int


def validate_symbol(symbol: str) -> str:
    """Valida el symbol en las tools read-only (mismo pattern que CanonicalOrder)."""
    import re
    if not re.fullmatch(SYMBOL_PATTERN, symbol):
        raise ValueError(f"invalid symbol {symbol!r}: expected {SYMBOL_PATTERN} (e.g. BTCUSDT)")
    return symbol
