"""Modelos Pydantic de entrada/salida y el CanonicalOrder (spec §3.3/§3.4)."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer, model_validator


def _plain_decimal(value: PlainDecimal) -> str:
    """Serializa SIEMPRE en notación posicional: nunca científica.

    `str(Decimal("0.00000000"))` es `"0E-8"`, y Binance devuelve ceros con escala
    (`locked` en cero, precios diminutos). El schema que Pydantic autogenera para
    `Decimal` rechaza esa forma, así que un balance normal rompía la validación de
    salida del tool. `format(d, "f")` conserva la escala y evita el exponente.
    """
    return format(value, "f")


# Política única de serialización de decimales del sistema. Todo campo decimal de todo
# modelo usa esto: el bug no era de un tool, era de cada `Decimal` expuesto.
PlainDecimal = Annotated[
    Decimal, PlainSerializer(_plain_decimal, return_type=str, when_used="always")
]

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
    quantity: PlainDecimal | None = None
    quote_quantity: PlainDecimal | None = None
    price: PlainDecimal | None = None
    time_in_force: TimeInForce | None = None
    env: Env

    @model_validator(mode="after")
    def _check(self) -> CanonicalOrder:
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
    effective_qty: PlainDecimal | None
    price: PlainDecimal | None
    est_notional: PlainDecimal | None
    est_commission: PlainDecimal | None
    env: Env
    warnings: list[str] = []
    feasible: bool
    reason: str | None = None


class OrderProposal(BaseModel):
    intent_id: str | None = None
    expires_at: int | None = None
    # NO autoritativa; el texto del diálogo lo renderiza el confirmador desde SU estimación.
    server_estimate: OrderPreview | None = None
    # Poblado cuando la propuesta no procede (ej. orden ya no cancelable, confirmador caído).
    error: ToolError | None = None


class Fill(BaseModel):
    price: PlainDecimal
    qty: PlainDecimal
    commission: PlainDecimal
    commission_asset: str


class OrderResult(BaseModel):
    order_id: int
    client_order_id: str
    status: str
    executed_qty: PlainDecimal
    cummulative_quote_qty: PlainDecimal
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
    free: PlainDecimal
    locked: PlainDecimal


class OpenOrder(BaseModel):
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    type: str
    price: PlainDecimal
    orig_qty: PlainDecimal
    executed_qty: PlainDecimal
    status: str
    time_in_force: str
    time: int


class PriceTicker(BaseModel):
    symbol: str
    price: PlainDecimal


class AccountInfo(BaseModel):
    can_trade: bool
    commission_rates: dict[str, PlainDecimal]
    account_type: str
    key_permissions: KeyPermissions | None = None


# --- Capa 2: market data + indicadores (read-only). OHLCV en Decimal (E3); floats. ---

class Kline(BaseModel):
    """Vela OHLCV. OHLCV en Decimal por consistencia con capa 1 (E3)."""
    open_time: int
    open: PlainDecimal
    high: PlainDecimal
    low: PlainDecimal
    close: PlainDecimal
    volume: PlainDecimal
    close_time: int


class Ticker24h(BaseModel):
    """Stats rolling 24h de un par."""
    symbol: str
    price_change_pct: PlainDecimal
    high: PlainDecimal
    low: PlainDecimal
    volume: PlainDecimal
    last: PlainDecimal


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
    price: PlainDecimal
    suggested_stop: PlainDecimal | None = None
    suggested_target: PlainDecimal | None = None
    atr: float
    disclaimer: str
    as_of: int


def validate_symbol(symbol: str) -> str:
    """Valida el symbol en las tools read-only (mismo pattern que CanonicalOrder)."""
    import re
    if not re.fullmatch(SYMBOL_PATTERN, symbol):
        raise ValueError(f"invalid symbol {symbol!r}: expected {SYMBOL_PATTERN} (e.g. BTCUSDT)")
    return symbol


# --- Capa 5: datos de analista (derivados públicos + estructura de mercado). ---
# Precios en Decimal (E3); ratios/métricas en float; campos degradables en None + notes.


class DerivativesSnapshot(BaseModel):
    """Termómetro de apalancamiento de un par (endpoints PÚBLICOS de futures, sin firma).

    `last_funding_rate` > 0 = longs pagan (positioning alcista); sostenido > 0.0005/8h =
    longs apiñados. `funding_history` = últimas N tasas (más antigua primero). En
    BINANCE_ENV=testnet estos datos son sintéticos (lo dice el disclaimer)."""
    symbol: str
    mark_price: PlainDecimal
    index_price: PlainDecimal
    last_funding_rate: float
    next_funding_time: int
    funding_history: list[float]
    open_interest: PlainDecimal
    as_of: int
    disclaimer: str


class MarketStructure(BaseModel):
    """Estructura del mercado crypto completo (fuentes públicas, independientes de
    BINANCE_ENV). CADA bloque degrada a None si su fuente falla — mirar `notes`.

    Lectura: `kb://glossary` y `kb://frameworks/cycle-analysis`."""
    fear_greed: int | None
    fear_greed_label: str | None
    fear_greed_week: list[int]
    btc_dominance_pct: float | None
    total_market_cap_usd: float | None
    btc_ath_usd: PlainDecimal | None
    btc_ath_date: str | None
    btc_ath_change_pct: float | None
    mempool_fee_fast_sat_vb: int | None
    hashrate_avg_ehs: float | None
    notes: list[str]
    as_of: int
    disclaimer: str


# --- Capa 6: analytics (frameworks calculados; float salvo precios). ---


class CycleAnalysis(BaseModel):
    """Inputs objetivos de posición de ciclo — la INTERPRETACIÓN la hace el cliente con
    `kb://frameworks/cycle-analysis`. `mayer_multiple` = precio / MA200 diaria."""
    symbol: str
    price: PlainDecimal
    ma200d: PlainDecimal | None
    mayer_multiple: float | None
    ath_usd: PlainDecimal | None
    drawdown_from_ath_pct: float | None
    est_next_halving: str
    notes: list[str]
    as_of: int
    disclaimer: str


class PortfolioPosition(BaseModel):
    """Una posición valorizada. `cost_basis`/`pnl_pct` sólo si el usuario aportó costos."""
    asset: str
    amount: PlainDecimal
    price_usdt: PlainDecimal | None
    value_usdt: PlainDecimal | None
    weight_pct: float | None
    cost_basis: PlainDecimal | None
    pnl_pct: float | None


class PortfolioReport(BaseModel):
    """Valorización + concentración + break-even NETO paramétrico (sin datos personales
    embebidos: cost_basis/tax_rate/spread son SIEMPRE parámetros del usuario)."""
    positions: list[PortfolioPosition]
    total_value_usdt: PlainDecimal
    top_concentration_pct: float | None
    net_breakeven_note: str | None
    notes: list[str]
    as_of: int
    disclaimer: str


class AssetRisk(BaseModel):
    """Métricas de riesgo de un activo (ventanas en días de velas 1d)."""
    symbol: str
    realized_vol_30d_pct: float | None
    realized_vol_90d_pct: float | None
    max_drawdown_pct: float | None
    correlation_btc_90d: float | None


class RiskReport(BaseModel):
    """Riesgo del portafolio: vol/drawdown/correlación por activo. La interpretación
    (sizing) vive en `kb://discipline` regla 2."""
    assets: list[AssetRisk]
    notes: list[str]
    as_of: int
    disclaimer: str


# --- Capa 6+ (v1.2): backtests de la doctrina (DCA / grilla de cosecha). ---


class DcaBacktestResult(BaseModel):
    """Simulación histórica de un plan DCA mecánico. NO es predicción (start-date
    sensitivity real — probar varias ventanas). Comparación honesta vs lump-sum."""
    symbol: str
    months: int
    monthly_quote: PlainDecimal
    total_invested: PlainDecimal
    accumulated_qty: PlainDecimal
    avg_cost: PlainDecimal
    value_now: PlainDecimal
    pnl_pct: float
    lump_sum_value_now: PlainDecimal
    max_drawdown_pct: float
    first_buy_date: str
    last_buy_date: str
    as_of: int
    disclaimer: str


class HarvestFill(BaseModel):
    """Un tramo de la grilla ejecutado en la simulación (fill al nivel, como limit)."""
    date: str
    level: PlainDecimal
    qty_sold: PlainDecimal
    proceeds: PlainDecimal


class HarvestBacktestResult(BaseModel):
    """Simulación de una grilla de cosecha pre-comprometida sobre cierres diarios.
    Cada nivel dispara UNA vez (cruce al alza). Comparación vs puro hold."""
    symbol: str
    initial_qty: PlainDecimal
    fills: list[HarvestFill]
    remaining_qty: PlainDecimal
    total_proceeds: PlainDecimal
    final_value: PlainDecimal
    pure_hold_value: PlainDecimal
    window_start: str
    window_end: str
    as_of: int
    disclaimer: str
