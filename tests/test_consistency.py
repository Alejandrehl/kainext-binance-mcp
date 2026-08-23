"""Gate anti-drift: el CI falla cuando la documentación deja de describir el producto.

Los conteos del README, la versión repartida en cuatro archivos y el alcance declarado
se mantenían a mano. Todo lo que se mantiene a mano se desincroniza — ya pasó: la
cápsula del HQ decía "18 tools" cuando eran 25 desde hacía versiones.

La única defensa que funciona es que el build caiga. Este archivo es esa defensa.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kainext_binance_mcp import server as srv
from kainext_binance_mcp.knowledge import _RESOURCES

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _registered_tool_names() -> set[str]:
    """Registra las tools en una MCPServer aislada (mismo patrón que test_server_tools)."""
    from mcp.server.mcpserver import MCPServer

    previous = srv.mcp
    try:
        srv.mcp = MCPServer("consistency")
        srv._register_tools(MagicMock(), MagicMock(), MagicMock(), is_testnet=True)
        return {t.name for t in srv.mcp._tool_manager.list_tools()}
    finally:
        srv.mcp = previous


def _readme_counts() -> dict[str, int]:
    """La línea del README que promete N tools / N prompts / N recursos."""
    m = re.search(
        r"\*\*(\d+) tools\*\*, \*\*(\d+) analyst prompts\*\* and \*\*(\d+) knowledge resources\*\*",
        README,
    )
    assert m, "El README ya no declara los conteos en el formato esperado"
    return {"tools": int(m[1]), "prompts": int(m[2]), "resources": int(m[3])}


# ── 1. Versión en lockstep ────────────────────────────────────────────────────────────

def test_version_is_identical_everywhere() -> None:
    """Un release con la versión desalineada rompe el MCP Registry en silencio."""
    version = PYPROJECT["project"]["version"]

    server_json = (ROOT / "server.json").read_text(encoding="utf-8")
    in_server_json = re.findall(r'"version"\s*:\s*"([^"]+)"', server_json)
    assert in_server_json, "server.json sin campo version"
    assert set(in_server_json) == {version}, (version, in_server_json)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # `[Unreleased]` es practica estandar de Keep a Changelog: se salta y se compara
    # contra la primera entrada VERSIONADA.
    versioned = [h for h in re.findall(r"^## \[([^\]]+)\]", changelog, re.M)
                 if h.lower() != "unreleased"]
    assert versioned and versioned[0] == version, (version, versioned[:1])


# ── 2/3/4. Los conteos del README describen lo que el servidor realmente expone ───────

def test_readme_tool_count_matches_registered_tools() -> None:
    names = _registered_tool_names()
    assert len(names) == _readme_counts()["tools"], sorted(names)


def test_readme_tool_table_lists_every_registered_tool() -> None:
    """No basta el número: la tabla tiene que nombrarlas todas."""
    documented = set(re.findall(r"^\| *`(binance_[a-z0-9_]+)`", README, re.M))
    missing = _registered_tool_names() - documented
    assert not missing, f"tools registradas pero sin fila en el README: {sorted(missing)}"


def test_readme_prompt_count_matches_registered_prompts() -> None:
    from kainext_binance_mcp.knowledge import prompts as p

    registered = {
        name
        for name, obj in vars(p).items()
        if callable(obj) and not name.startswith("_") and obj.__module__ == p.__name__
    }
    assert len(registered) == _readme_counts()["prompts"], sorted(registered)


def test_resources_are_consistent_across_registry_files_and_readme() -> None:
    content_dir = ROOT / "src" / "kainext_binance_mcp" / "knowledge" / "content"
    files = {f.name for f in content_dir.glob("*.md")}
    declared = {fname for fname, _title in _RESOURCES.values()}
    assert declared == files, (sorted(declared), sorted(files))
    assert len(_RESOURCES) == _readme_counts()["resources"]


# ── 5. El alcance declarado no contradice lo que el paquete expone ────────────────────

def _claims_spot_only(text: str) -> bool:
    """Dice 'spot' sin nombrar futuros: promete un alcance que ya no es el real."""
    low = text.lower()
    return "spot" in low and "futur" not in low


def test_declared_scope_matches_what_the_package_ships() -> None:
    """Si el paquete trae el motor de futuros, ni la descripción ni `_INSTRUCTIONS`
    pueden seguir diciendo que esto es solo spot.

    `_INSTRUCTIONS` no es documentación: MCPServer lo inyecta en TODA sesión de todo
    cliente MCP. Dejarlo obsoleto le da reglas viejas a cada sesión de IA.
    """
    ships_futures = (ROOT / "src" / "kainext_binance_mcp" / "futures").is_dir()
    if not ships_futures:
        pytest.skip("el paquete aún no expone research de futuros")
    assert not _claims_spot_only(PYPROJECT["project"]["description"])
    assert not _claims_spot_only(srv._INSTRUCTIONS)


def test_instructions_actually_reach_the_server_object() -> None:
    """El texto tiene que llegar a `instructions`, no a `title`.

    Trampa real del upgrade a mcp 2.0: en el FastMCP viejo el 2do posicional era
    `instructions`; en `MCPServer` es `title`. Pasarlo posicional deja `instructions=None`
    y la doctrina deja de inyectarse en CADA sesion, en silencio y sin que falle nada.
    Ningun test lo miraba: por eso existe este.
    """
    assert srv.mcp.instructions == srv._INSTRUCTIONS
    assert srv.mcp.title != srv._INSTRUCTIONS, "las instrucciones se fueron al title"


def test_instructions_still_ground_the_client_in_the_doctrine() -> None:
    """Cambie lo que cambie el alcance, el grounding en la doctrina no se puede perder."""
    assert "kb://discipline" in srv._INSTRUCTIONS
    assert "kb://research/no-edge" in srv._INSTRUCTIONS
