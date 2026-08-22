"""Capa 7 — el conocimiento del consultor (spec Analyst Edition, 22-08-2026).

Expone la metodología del analista por las DOS superficies MCP que no son tools:
- **Resources** (`kb://…`): frameworks, registry de fuentes con sesgos, disciplina,
  la evidencia de no-edge, calendario macro y glosario. Markdown estático embebido
  en el paquete (`content/*.md`) — el wheel los incluye (hatchling empaqueta los
  archivos no-Python del paquete; verificado).
- **Prompts**: playbooks que orquestan las tools + resources en una metodología.

Los clientes MCP NO leen resources solos: el cableado que hace que el conocimiento
actúe está en (a) las instructions del server, (b) los docstrings de las tools
interpretativas, y (c) el primer paso de cada prompt (leer sus resources).
"""
from __future__ import annotations

from importlib import resources as _res

from mcp.server.fastmcp import FastMCP

from kainext_binance_mcp.knowledge import prompts as _prompts

# uri -> (archivo en content/, título para el cliente)
_RESOURCES: dict[str, tuple[str, str]] = {
    "kb://discipline": ("discipline.md", "Investment discipline (the operating doctrine)"),
    "kb://research/no-edge": ("no-edge.md", "Research: no robust technical edge (walk-forward)"),
    "kb://sources": ("sources.md", "Source registry with bias annotations"),
    "kb://frameworks/news-analysis": ("news-analysis.md", "News analysis method"),
    "kb://frameworks/cycle-analysis": ("cycle-analysis.md", "Cycle analysis framework"),
    "kb://frameworks/token-value": ("token-value.md", "Token value-capture framework"),
    "kb://macro-calendar": ("macro-calendar.md", "Macro calendar (FOMC/CPI/halving)"),
    "kb://glossary": ("glossary.md", "Glossary with interpretive readings"),
}


def read_content(filename: str) -> str:
    """Lee un .md embebido del paquete (funciona instalado desde wheel o editable)."""
    return (_res.files("kainext_binance_mcp.knowledge") / "content" / filename).read_text(
        encoding="utf-8")


def register_knowledge(mcp: FastMCP) -> None:
    """Registra resources + prompts sobre la instancia dada.

    Mismo patrón que `_register_tools`: se llama desde `main()` (y desde los tests con
    una FastMCP fresca). NO usar decoradores externos sobre las funciones registradas
    (rompe la introspección de FastMCP — gotcha documentado en server.py).
    """
    for uri, (filename, title) in _RESOURCES.items():
        # OJO: la función NO puede tener parámetros (FastMCP la trataría como template).
        # Se fija el filename con una factory para evitar el late-binding del loop.
        def _make_reader(fname: str):  # type: ignore[no-untyped-def]  # helper local
            def _reader() -> str:
                return read_content(fname)
            return _reader

        reader = _make_reader(filename)
        reader.__doc__ = title
        mcp.resource(uri, name=filename.removesuffix(".md"), title=title,
                     mime_type="text/markdown")(reader)

    mcp.prompt(title="Full portfolio review (methodical)")(_prompts.portfolio_review)
    mcp.prompt(title="Asset thesis (value-capture framework)")(_prompts.asset_thesis)
    mcp.prompt(title="Market briefing (what to read today)")(_prompts.market_briefing)
    mcp.prompt(title="Portfolio risk check")(_prompts.risk_check)
    mcp.prompt(title="Design a disciplined DCA plan")(_prompts.dca_plan)
