"""Tools de lectura spot (read key). Spec §3.1."""
from __future__ import annotations
from decimal import Decimal
from typing import Any
from binance.client import Client
from kainext_binance_mcp.models import AssetBalance, OpenOrder, PriceTicker
from kainext_binance_mcp.guard import perms_from_api


def get_balance(client: Client) -> list[AssetBalance]:
    acct = client.get_account()
    out: list[AssetBalance] = []
    for b in acct["balances"]:
        free, locked = Decimal(b["free"]), Decimal(b["locked"])
        if free > 0 or locked > 0:
            out.append(AssetBalance(asset=b["asset"], free=free, locked=locked))
    return out


def get_price(client: Client, symbol: str) -> PriceTicker:
    t = client.get_symbol_ticker(symbol=symbol)
    return PriceTicker(symbol=t["symbol"], price=Decimal(t["price"]))


def _to_open_order(o: dict[str, Any]) -> OpenOrder:
    return OpenOrder(
        symbol=o["symbol"], order_id=o["orderId"], client_order_id=o["clientOrderId"],
        side=o["side"], type=o["type"], price=Decimal(o["price"]),
        orig_qty=Decimal(o["origQty"]), executed_qty=Decimal(o["executedQty"]),
        status=o["status"], time_in_force=o["timeInForce"], time=o["time"],
    )


def get_open_orders(client: Client, symbol: str | None = None) -> list[OpenOrder]:
    raw = client.get_open_orders(symbol=symbol) if symbol else client.get_open_orders()
    return [_to_open_order(o) for o in raw]


def get_order_history(client: Client, symbol: str, limit: int = 50) -> list[OpenOrder]:
    raw = client.get_all_orders(symbol=symbol, limit=limit)
    return [_to_open_order(o) for o in raw]


def get_account_info(client: Client, *, is_testnet: bool) -> "AccountInfo":
    from kainext_binance_mcp.models import AccountInfo
    acct = client.get_account()
    rates = {k: Decimal(v) for k, v in acct.get("commissionRates", {}).items()}
    perms = None
    if not is_testnet:  # apiRestrictions es SAPI: no existe en testnet
        perms = perms_from_api(client.get_account_api_permissions())
    return AccountInfo(can_trade=acct["canTrade"],
                       commission_rates=rates or {"maker": Decimal("0"), "taker": Decimal("0")},
                       account_type=acct.get("accountType", "SPOT"), key_permissions=perms)
