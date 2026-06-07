"""Intents y su máquina de estados (spec §4.3b). Estado en memoria del confirmador."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Callable
from kainext_binance_mcp.models import CanonicalOrder, OrderResult, ToolError

_TERMINAL = {"executed", "rejected", "expired", "failed"}


class IntentStateError(Exception):
    pass


@dataclass
class Intent:
    intent_id: str
    order: CanonicalOrder | None
    created_at: int
    expires_at: int
    _state: str = "pending"
    approved: bool = False
    result: OrderResult | None = None
    error: ToolError | None = None
    # Sólo poblados para intents de cancelación (en ese caso `order` es None):
    kind: str = "order"
    cancel_symbol: str | None = None
    cancel_order_id: int | None = None

    @property
    def state(self) -> str:
        return self._state


@dataclass
class IntentStore:
    ttl_seconds: int
    now: Callable[[], int]
    _items: dict[str, Intent] = field(default_factory=dict)

    def register(self, order: CanonicalOrder) -> str:
        iid = uuid.uuid4().hex
        t = self.now()
        self._items[iid] = Intent(intent_id=iid, order=order, created_at=t,
                                  expires_at=t + self.ttl_seconds)
        return iid

    def register_cancel(self, symbol: str, order_id: int) -> str:
        iid = uuid.uuid4().hex
        t = self.now()
        self._items[iid] = Intent(intent_id=iid, order=None, created_at=t,
                                  expires_at=t + self.ttl_seconds, kind="cancel",
                                  cancel_symbol=symbol, cancel_order_id=order_id)
        return iid

    def pending_count(self) -> int:
        """Cuántos intents siguen pendientes (no terminales ni expirados).
        Recorre por get() para que la expiración perezosa se aplique."""
        n = 0
        for iid in list(self._items):
            if self.get(iid)._state == "pending":
                n += 1
        return n

    def get(self, iid: str) -> Intent:
        it = self._items.get(iid)
        if it is None:
            raise KeyError(iid)
        if it._state == "pending" and self.now() >= it.expires_at:
            it._state = "expired"
        return it

    def _guard_pending(self, it: Intent) -> None:
        if it._state in _TERMINAL:
            raise IntentStateError(f"intent {it.intent_id} ya es terminal ({it._state})")

    def mark_approved(self, iid: str) -> None:
        it = self.get(iid); self._guard_pending(it); it.approved = True

    def mark_rejected(self, iid: str) -> None:
        it = self.get(iid); self._guard_pending(it); it._state = "rejected"

    def mark_executed(self, iid: str, result: OrderResult) -> None:
        it = self.get(iid); self._guard_pending(it)
        it.result = result; it._state = "executed"

    def mark_failed(self, iid: str, error: ToolError) -> None:
        it = self.get(iid); self._guard_pending(it)
        it.error = error; it._state = "failed"
