"""Modelos Pydantic de entrada/salida y el CanonicalOrder (spec §3.3/§3.4)."""
from __future__ import annotations
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, model_validator

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT"]
Env = Literal["testnet", "mainnet"]
TimeInForce = Literal["GTC", "IOC", "FOK"]


class CanonicalOrder(BaseModel):
    """Lo ÚNICO que viaja por IPC al confirmador. Sin texto, sin id, sin hash."""
    model_config = {"frozen": True}
    symbol: str
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
                raise ValueError("LIMIT requiere price")
            if self.time_in_force is None:
                raise ValueError("LIMIT requiere time_in_force (default GTC en la tool)")
            if self.quote_quantity is not None:
                raise ValueError("quote_quantity sólo aplica a MARKET")
            if self.quantity is None:
                raise ValueError("LIMIT requiere quantity")
        if self.type == "MARKET":
            if self.price is not None:
                raise ValueError("MARKET no acepta price")
            if self.time_in_force is not None:
                raise ValueError("MARKET no acepta time_in_force")
        if (self.quantity is None) == (self.quote_quantity is None):
            raise ValueError("exactamente uno de quantity / quote_quantity")
        for v in (self.quantity, self.quote_quantity, self.price):
            if v is not None and v <= 0:
                raise ValueError("montos deben ser > 0")
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
