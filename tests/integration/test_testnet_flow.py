"""Test de integración end-to-end contra Binance **testnet** (plata falsa).

Ejercita el flujo real de los dos procesos (spec §5.2) con clientes REALES de
Binance testnet, pero con el clic del diálogo **stubeado** (nunca abre osascript):

    get_balance
      → spot_order_propose (LIMIT BUY a -50% del precio: NO se llena)
      → spot_order_status hasta "executed" (orden colocada, queda NEW/abierta)
      → get_open_orders (la orden aparece)
      → cancel_order_propose + cancel_order_status → CANCELED

Arquitectura ejercitada:
- **Confirmador:** `ipc.serve(...)` corriendo en un hilo daemon, con el client/estimator
  de la TRADE key. `ask_confirmation` se reemplaza por un stub que SIEMPRE confirma
  (monkeypatch sobre `kainext_binance_mcp_confirmer.dialog.ask_confirmation`), así el
  flujo de integración NUNCA abre un diálogo real de osascript (apto para CI headless).
- **Server:** `IpcClient` apuntando al MISMO socket + las tools de `tools/write.py`
  y las lecturas de `tools/read.py` con el client de la READ key.

Cómo correrlo (requiere keys de testnet — sacalas de https://testnet.binance.vision):

    export BINANCE_ENV=testnet
    export BINANCE_TRADE_API_KEY=...     # key de testnet con spot trading ON
    export BINANCE_TRADE_API_SECRET=...
    export BINANCE_READ_API_KEY=...      # puede ser la MISMA key de testnet
    export BINANCE_READ_API_SECRET=...
    .venv/bin/python -m pytest -m integration -v

En testnet `apiRestrictions` no existe (SAPI no está) → NO hay guard de permisos:
una sola key de testnet alcanza para read + trade. Sin `BINANCE_TRADE_API_KEY` en el
entorno el test SKIPEA limpio (no toca red, no toca Binance).
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from decimal import Decimal

import pytest

# ── Gate de skip: sin la trade key de testnet en el entorno, no hay nada que correr.
_HAS_KEYS = bool(os.environ.get("BINANCE_TRADE_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _HAS_KEYS, reason="requiere keys de testnet (BINANCE_TRADE_API_KEY)"),
]

_SYMBOL = "BTCUSDT"
_POLL_TIMEOUT_S = 30.0


def _wait_socket(path: str, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return
        time.sleep(0.02)
    raise AssertionError(f"el confirmador no creó el socket {path} a tiempo")


def _poll_status(status_fn, intent_id: str, *, want: set[str], timeout: float = _POLL_TIMEOUT_S):
    """Poll del two-phase status hasta un estado terminal esperado (o timeout)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = status_fn(ipc=_IPC, intent_id=intent_id)
        if last.state in want:
            return last
        if last.state in ("rejected", "expired", "failed"):
            raise AssertionError(f"intent {intent_id} terminó en {last.state}: {last.error}")
        time.sleep(0.25)
    raise AssertionError(f"intent {intent_id} no llegó a {want} (último: {last.state if last else None})")


# Compartido entre fixture y helper de poll (se setea en la fixture).
_IPC = None


@pytest.fixture
def testnet_stack(monkeypatch):
    """Levanta confirmador (serve en hilo) + server (IpcClient) contra testnet real."""
    from kainext_binance_mcp.client import make_client
    from kainext_binance_mcp.config import load_confirmer_settings, load_server_settings
    from kainext_binance_mcp.ipc import IpcClient, serve
    from kainext_binance_mcp.intents import IntentStore
    from kainext_binance_mcp.market import MarketEstimator, parse_symbol_filters

    # Clic SIEMPRE Confirmar: el flujo de integración jamás abre osascript real.
    import kainext_binance_mcp_confirmer.dialog as dialog
    monkeypatch.setattr(dialog, "ask_confirmation", lambda text: True)

    # Clients reales de testnet (read + trade; en testnet puede ser la misma key).
    trade_settings = load_confirmer_settings(os.environ)
    server_settings = load_server_settings(os.environ)
    assert trade_settings.is_testnet, "este test SOLO corre con BINANCE_ENV=testnet"

    trade_client = make_client(trade_settings)   # ejecuta órdenes (confirmador)
    read_client = make_client(server_settings)   # sólo lee (server)

    def _estimator(client):
        return MarketEstimator(
            get_filters=lambda s: parse_symbol_filters(client.get_symbol_info(s)),
            get_price=lambda s: Decimal(client.get_symbol_ticker(symbol=s)["price"]),
        )

    # Socket temporal aislado (no el de producción ~/Library/Application Support/...).
    tmpdir = tempfile.mkdtemp(prefix="kbm-itest-")
    sock_path = os.path.join(tmpdir, "confirmer.sock")

    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    lock = threading.Lock()
    t = threading.Thread(
        target=serve,
        args=(sock_path, store, trade_client, "itest-nonce", lock, _estimator(trade_client)),
        daemon=True,
    )
    t.start()
    _wait_socket(sock_path)

    global _IPC
    _IPC = IpcClient(sock_path)
    yield _IPC, read_client, _estimator(read_client)
    _IPC = None


def test_full_testnet_flow(testnet_stack):
    from kainext_binance_mcp.tools import read as read_tools
    from kainext_binance_mcp.tools import write as write_tools

    ipc, read_client, server_market = testnet_stack

    # 1) get_balance — debe responder sin error (puede venir vacío en una cuenta nueva).
    balances = read_tools.get_balance(read_client)
    assert isinstance(balances, list)

    # 2) spot_order_propose — LIMIT BUY a un precio 50% BAJO el mercado → NO se llena.
    price_now = Decimal(read_client.get_symbol_ticker(symbol=_SYMBOL)["price"])
    far_price = price_now / 2
    proposal = write_tools.spot_order_propose(
        ipc=ipc, market=server_market, symbol=_SYMBOL, side="BUY", type="LIMIT",
        env="testnet", quantity=Decimal("0.001"), price=far_price, time_in_force="GTC",
    )
    assert proposal.intent_id, "propose debe devolver un intent_id"

    # 3) spot_order_status hasta "executed" (la orden se COLOCA; queda abierta, no fill).
    status = _poll_status(write_tools.spot_order_status, proposal.intent_id, want={"executed"})
    assert status.result is not None
    order_id = status.result.order_id
    assert order_id

    # 4) get_open_orders — la orden recién colocada debe aparecer.
    open_orders = read_tools.get_open_orders(read_client, _SYMBOL)
    assert any(o.order_id == order_id for o in open_orders), \
        f"la orden {order_id} debería estar abierta: {[o.order_id for o in open_orders]}"

    # 5) cancel_order_propose + cancel_order_status → CANCELED.
    cancel_prop = write_tools.cancel_order_propose(
        ipc=ipc, client=read_client, symbol=_SYMBOL, order_id=order_id, env="testnet")
    assert cancel_prop.error is None, f"cancel_propose falló: {cancel_prop.error}"
    assert cancel_prop.intent_id

    cancel_status = _poll_status(
        write_tools.cancel_order_status, cancel_prop.intent_id, want={"executed"})
    assert cancel_status.result is not None
    assert cancel_status.result.status == "CANCELED"

    # Verificación final: la orden ya NO está abierta.
    open_after = read_tools.get_open_orders(read_client, _SYMBOL)
    assert not any(o.order_id == order_id for o in open_after), \
        "la orden cancelada no debería seguir abierta"
