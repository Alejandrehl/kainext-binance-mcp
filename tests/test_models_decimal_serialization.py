"""D1 — Decimal NUNCA debe salir en notación científica.

Bug real en producción: Binance devuelve "0.00000000" para un `locked` en cero,
`str(Decimal("0.00000000"))` es "0E-8", y el output schema que Pydantic genera para
Decimal lo rechaza -> `binance_get_balance` fallaba con
`Output validation error: '0E-8' does not match ...`.

El fix vive en un solo lugar (`models.Money`), asi que estos tests barren TODOS los
modelos con campos Decimal, no solo el que reporto el bug.
"""
from decimal import Decimal

import pytest
from pydantic import BaseModel

from kainext_binance_mcp import models
from kainext_binance_mcp.models import (
    AssetBalance,
    DerivativesSnapshot,
    Kline,
    OrderPreview,
    PriceTicker,
    Ticker24h,
)

# Valores que disparan notacion cientifica en str(Decimal(...)).
SCI = ["0.00000000", "1E+3", "1E-9", "-0.00010000", "0E-8"]


@pytest.mark.parametrize("raw", SCI)
def test_asset_balance_never_serializes_scientific(raw: str) -> None:
    dumped = AssetBalance(asset="BTC", free=Decimal(raw), locked=Decimal("0.00000000")).model_dump(
        mode="json"
    )
    assert "E" not in dumped["free"].upper(), dumped
    assert dumped["locked"] == "0.00000000"


def test_zero_locked_round_trips_the_exact_binance_string() -> None:
    """El caso exacto que rompio en produccion."""
    b = AssetBalance(asset="BTC", free=Decimal("0.04111599"), locked=Decimal("0.00000000"))
    assert b.model_dump(mode="json") == {
        "asset": "BTC",
        "free": "0.04111599",
        "locked": "0.00000000",
    }


def test_decimal_schema_has_no_fragile_regex() -> None:
    """El pattern autogenerado para Decimal es lo que rechazaba '0E-8'.

    Con el serializer propio el campo es un string simple: sin pattern, sin trampa.
    """
    props = AssetBalance.model_json_schema(mode="serialization")["properties"]
    for field in ("free", "locked"):
        assert "pattern" not in props[field], props[field]
        assert props[field]["type"] == "string"


def _walk(node: object):
    """Recorre un JSON Schema completo (incluidos $defs) nodo por nodo."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _all_models() -> list[type[BaseModel]]:
    return [
        obj
        for obj in vars(models).values()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel
    ]


def test_no_model_anywhere_exposes_the_fragile_decimal_pattern() -> None:
    """Guard de politica: barre TODOS los modelos del modulo, no una lista a mano.

    Si alguien agrega un campo `Decimal` crudo en vez de `PlainDecimal`, Pydantic le
    autogenera el pattern que rechaza '0E-8' y este test cae. Es el unico modo de que
    el bug no vuelva por una puerta distinta a la que lo encontramos.
    """
    offenders = []
    for model in _all_models():
        for node in _walk(model.model_json_schema(mode="serialization")):
            if "0*" in str(node.get("pattern", "")):
                offenders.append((model.__name__, node))
    assert not offenders, offenders


@pytest.mark.parametrize("raw", SCI)
def test_decimal_fields_never_serialize_scientific(raw: str) -> None:
    """Los campos decimales de cualquier modelo instanciable salen en notacion plana."""
    value = Decimal(raw)
    samples = [
        Kline(open_time=0, open=value, high=value, low=value, close=value, volume=value,
              close_time=1),
        PriceTicker(symbol="BTCUSDT", price=value),
        Ticker24h(symbol="BTCUSDT", price_change_pct=value, high=value, low=value,
                  volume=value, last=value),
        DerivativesSnapshot(symbol="BTCUSDT", mark_price=value, index_price=value,
                            last_funding_rate=0.0, next_funding_time=0, funding_history=[],
                            open_interest=value, as_of=0, disclaimer="x"),
        OrderPreview(effective_qty=value, price=value, est_notional=value,
                     est_commission=value, env="testnet", feasible=True),
    ]
    for model in samples:
        decimal_fields = [
            name for name, f in type(model).model_fields.items() if "Decimal" in str(f.annotation)
        ]
        assert decimal_fields, f"{type(model).__name__} sin campos decimales?"
        dumped = model.model_dump(mode="json")
        for name in decimal_fields:
            assert "E" not in str(dumped[name]).upper(), f"{type(model).__name__}.{name}"


def test_validation_still_accepts_str_float_int() -> None:
    """El serializer no debe cambiar la validacion de entrada."""
    assert AssetBalance(asset="BTC", free="1.5", locked=0).free == Decimal("1.5")
