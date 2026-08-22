"""Smoke manual del gate humano contra TESTNET (plata falsa).

Levanta el confirmador real (socket + estimator + trade key de testnet), propone
una orden LIMIT BUY que NO se llena (precio dentro de PERCENT_PRICE_BY_SIDE) y
dispara el DIÁLOGO NATIVO real. El operador clickea Confirmar/Cancelar.
- Confirmar  -> coloca la orden testnet, la muestra, y la cancela al final.
- Cancelar   -> no se ejecuta nada (verifica el gate).

Uso:
  BINANCE_ENV=testnet BINANCE_TRADE_API_KEY=... BINANCE_TRADE_API_SECRET=... \
  .venv/bin/python examples/smoke_dialog_testnet.py
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from decimal import ROUND_UP, Decimal

from kainext_binance_mcp import ipc
from kainext_binance_mcp.intents import IntentStore
from kainext_binance_mcp.models import CanonicalOrder
from kainext_binance_mcp_confirmer import dialog
from kainext_binance_mcp_confirmer.__main__ import _make_estimator, bootstrap

SYMBOL = "BTCUSDT"
dialog._DIALOG_TIMEOUT_S = 90  # más holgura para el clic manual


def _valid_non_filling_limit_buy(client) -> CanonicalOrder:
    info = client.get_symbol_info(SYMBOL)
    filt = {f["filterType"]: f for f in info["filters"]}
    last = Decimal(client.get_symbol_ticker(symbol=SYMBOL)["price"])
    tick = Decimal(filt["PRICE_FILTER"]["tickSize"])
    step = Decimal(filt["LOT_SIZE"]["stepSize"])
    min_qty = Decimal(filt["LOT_SIZE"]["minQty"])
    notional_f = filt.get("NOTIONAL") or filt.get("MIN_NOTIONAL") or {}
    min_notional = Decimal(notional_f.get("minNotional", "5"))
    bid_down = Decimal(filt.get("PERCENT_PRICE_BY_SIDE", {}).get("bidMultiplierDown", "0.2"))

    raw_price = last * max(bid_down * Decimal("1.02"), Decimal("0.80"))
    price = (raw_price / tick).to_integral_value(rounding=ROUND_UP) * tick  # ceil al tick
    # qty ~ 2x min_notional, múltiplo de step, >= min_qty
    qty = (min_notional * 2 / price).quantize(step, rounding=ROUND_UP)
    if qty < min_qty:
        qty = min_qty
    if qty * price < min_notional:
        qty += step
    return CanonicalOrder(symbol=SYMBOL, side="BUY", type="LIMIT", quantity=qty,
                          price=price, time_in_force="GTC", env="testnet")


def main() -> None:
    settings, client = bootstrap(os.environ)
    assert settings.is_testnet, "ESTE SMOKE ES SOLO TESTNET — abortando."
    estimator = _make_estimator(client)
    order = _valid_non_filling_limit_buy(client)
    print(f"[smoke] Orden propuesta: {order.side} {order.quantity} {order.symbol} "
          f"@ {order.price} ({order.time_in_force}) env={order.env}", flush=True)

    sock_dir = tempfile.mkdtemp(prefix="kbm-smoke-")
    sock_path = os.path.join(sock_dir, "confirmer.sock")
    audit_path = os.path.join(sock_dir, "audit.log")
    store = IntentStore(ttl_seconds=300, now=lambda: int(time.time()))
    nonce = "smoke-nonce"
    lock = threading.Lock()

    t = threading.Thread(
        target=ipc.serve,
        args=(sock_path, store, client, nonce, lock, estimator),
        kwargs={"confirmer_env": settings.env, "audit_path": audit_path},
        daemon=True,
    )
    t.start()
    time.sleep(0.6)

    cli = ipc.IpcClient(sock_path)
    intent_id, _expires = cli.register(order)
    print(f"[smoke] intent {intent_id} registrado. "
          f"==> MIRÁ TU PANTALLA: debería aparecer un diálogo macOS. Clickeá Confirmar o Cancelar.",
          flush=True)

    final = None
    for _ in range(95):
        st = cli.status(intent_id)
        if st["state"] in ("executed", "rejected", "expired", "failed"):
            final = st
            break
        time.sleep(1)

    print(f"[smoke] ESTADO FINAL: {final}", flush=True)
    if final and final["state"] == "executed":
        res = final["result"]
        oid = res["order_id"]
        print(f"[smoke] ✅ Orden colocada en testnet — order_id={oid}, status={res['status']}", flush=True)
        # cancelar para dejar limpio
        try:
            client.cancel_order(symbol=SYMBOL, orderId=oid)
            print(f"[smoke] 🧹 Orden {oid} cancelada (cleanup).", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[smoke] (no se pudo cancelar {oid}: {e})", flush=True)
        # mostrar el audit log (sin secretos)
        if os.path.exists(audit_path):
            print(f"[smoke] audit.log:\n{open(audit_path).read().strip()}", flush=True)
    elif final and final["state"] == "rejected":
        print("[smoke] ⛔ Clickeaste CANCELAR — no se ejecutó NADA. Gate OK (rechazo).", flush=True)
    else:
        print("[smoke] ⚠️ No se confirmó (timeout/expired/failed). Si no viste el diálogo, "
              "puede estar detrás de otra ventana o requerir permiso de Automatización de macOS.", flush=True)


if __name__ == "__main__":
    main()
