"""Guards de permisos de API key vía apiRestrictions (spec §4.4)."""
from __future__ import annotations

from typing import Any

from kainext_binance_mcp.models import KeyPermissions


class GuardError(Exception):
    pass


def perms_from_api(api: dict[str, Any]) -> KeyPermissions:
    return KeyPermissions(
        enable_spot_and_margin_trading=bool(api.get("enableSpotAndMarginTrading", False)),
        enable_withdrawals=bool(api.get("enableWithdrawals", False)),
        permits_universal_transfer=bool(api.get("permitsUniversalTransfer", False)),
        enable_internal_transfer=bool(api.get("enableInternalTransfer", False)),
        enable_margin=bool(api.get("enableMargin", False)),
        enable_futures=bool(api.get("enableFutures", False)),
        enable_portfolio_margin_trading=bool(api.get("enablePortfolioMarginTrading", False)),
        ip_restrict=bool(api.get("ipRestrict", False)),
    )


def assert_trade_key_safe(p: KeyPermissions) -> None:
    """La trade key del confirmador. Nota: enableSpotAndMarginTrading agrupa spot+margin;
    la no-ejecución de margin se garantiza en código (nunca se llaman endpoints de margin)."""
    problems: list[str] = []
    if not p.enable_spot_and_margin_trading:
        problems.append("trade key does NOT have spot trading enabled (could not place orders)")
    if p.enable_withdrawals:
        problems.append("enableWithdrawals is ON (must be OFF)")
    if p.permits_universal_transfer:
        problems.append("permitsUniversalTransfer ON (can drain funds)")
    if p.enable_internal_transfer:
        problems.append("enableInternalTransfer ON (can move funds)")
    if p.enable_futures:
        problems.append("enableFutures ON (not in layer 1)")
    if p.enable_portfolio_margin_trading:
        problems.append("enablePortfolioMarginTrading ON")
    if not p.ip_restrict:
        problems.append("ipRestrict OFF (IP whitelist is mandatory)")
    if problems:
        raise GuardError("unsafe trade key: " + "; ".join(problems))


def assert_read_key_safe(p: KeyPermissions) -> None:
    """La read key del server: NO debe poder tradear/mover plata."""
    problems: list[str] = []
    if p.enable_spot_and_margin_trading:
        problems.append("read key has trading enabled (must be read-only)")
    if p.enable_withdrawals:
        problems.append("enableWithdrawals ON")
    if p.enable_futures:
        problems.append("enableFutures ON")
    if p.enable_margin:
        problems.append("enableMargin ON")
    if p.permits_universal_transfer:
        problems.append("permitsUniversalTransfer ON")
    if problems:
        raise GuardError("unsafe read key: " + "; ".join(problems))
