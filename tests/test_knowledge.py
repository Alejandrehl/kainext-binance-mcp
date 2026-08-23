"""Capa 7: resources kb:// + prompts (registro, contenido, render)."""
from __future__ import annotations

import asyncio

import pytest
from mcp.server.fastmcp import FastMCP

from kainext_binance_mcp.knowledge import _RESOURCES, read_content, register_knowledge


def _fresh() -> FastMCP:
    m = FastMCP("test")
    register_knowledge(m)
    return m


def test_all_resources_register_and_read_markdown() -> None:
    m = _fresh()
    listed = asyncio.run(m.list_resources())
    assert {str(r.uri) for r in listed} == set(_RESOURCES)
    for uri in _RESOURCES:
        content = list(asyncio.run(m.read_resource(uri)))[0].content
        assert isinstance(content, str) and len(content) > 300
        assert content.lstrip().startswith("#")  # markdown con título


def test_resource_content_has_no_personal_data() -> None:
    """Salvaguarda de privacidad: el conocimiento es genérico, sin datos del operador."""
    banned = ["alejandro", "kainext-hq", "clp", "$5.000.000", "106.661", "106661",
              "vault", "obsidian"]
    for _, (fname, _t) in _RESOURCES.items():
        text = read_content(fname).lower()
        for word in banned:
            assert word not in text, f"{fname} contiene {word!r}"


def test_discipline_and_no_edge_carry_the_doctrine() -> None:
    d = read_content("discipline.md").lower()
    assert "leverage" in d and "dca" in d and "position siz" in d
    n = read_content("no-edge.md").lower()
    assert "0 of 36" in n and "walk-forward" in n and "not alpha" in n


def test_discipline_keeps_the_two_regimes_separate() -> None:
    """La doctrina permite apalancamiento SOLO dentro de research sistematico validado.

    Lo que hace defendible esa apertura es la separacion: capital segregado, reglas
    escritas antes, correccion por multiple testing y circuit breaker. Si una edicion
    futura borra la separacion, queda una doctrina que dice "apalancate" sin condiciones
    — que es justo lo que no debe pasar.
    """
    d = read_content("discipline.md").lower()
    assert "two regimes" in d, "se perdio la separacion explicita entre portafolio y research"
    # El veto al apalancamiento discrecional NO se relaja.
    assert "discretionary directional leverage" in d
    # Y las condiciones duras siguen nombradas.
    for condition in ("out-of-sample", "multiple testing", "circuit breaker",
                      "segregated capital", "volatility targeting"):
        assert condition in d, f"la doctrina ya no exige: {condition}"


def test_prompts_register_and_render() -> None:
    m = _fresh()
    prompts = {p.name for p in asyncio.run(m.list_prompts())}
    assert prompts == {"portfolio_review", "asset_thesis", "market_briefing",
                       "risk_check", "dca_plan"}
    # requeridos y opcionales
    r = asyncio.run(m.get_prompt("asset_thesis", {"symbol": "BTCUSDT"}))
    text = r.messages[0].content.text
    assert "BTCUSDT" in text and "kb://frameworks/token-value" in text
    r2 = asyncio.run(m.get_prompt("market_briefing", {}))
    assert "kb://sources" in r2.messages[0].content.text


def test_prompt_missing_required_arg_raises() -> None:
    m = _fresh()
    with pytest.raises(Exception, match="[Mm]issing"):
        asyncio.run(m.get_prompt("dca_plan", {}))


def test_every_prompt_grounds_in_discipline() -> None:
    """El cableado anti-peso-muerto: TODOS los playbooks abren leyendo la doctrina."""
    m = _fresh()
    cases = {"portfolio_review": {}, "asset_thesis": {"symbol": "ETHUSDT"},
             "market_briefing": {}, "risk_check": {},
             "dca_plan": {"monthly_amount": "100"}}
    for name, args in cases.items():
        text = asyncio.run(m.get_prompt(name, args)).messages[0].content.text
        assert "kb://discipline" in text and "kb://research/no-edge" in text, name
        assert "not financial advice" in text.lower() or "financial advice" in text.lower()
