"""Handshake MCP real por stdio: lo unico que prueba el producto como lo ve un cliente.

El resto de la suite registra tools en una instancia aislada; nada arrancaba el servidor
ni hablaba el protocolo. Ese hueco importo de verdad en el upgrade a mcp 2.0: el 2do
posicional de `MCPServer` es `title`, no `instructions`, asi que la doctrina podia dejar
de inyectarse en cada sesion sin romper un solo test unitario.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_HAS_KEYS = bool(os.environ.get("BINANCE_READ_API_KEY") and os.environ.get("BINANCE_ENV"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _HAS_KEYS, reason="requiere BINANCE_ENV + BINANCE_READ_API_*"),
]

ROOT = Path(__file__).resolve().parent.parent.parent


class Server:
    """Cliente MCP minimo sobre el servidor lanzado como subproceso."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "kainext_binance_mcp.server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=ROOT, env=os.environ.copy(),
        )

    def send(self, msg: dict[str, object]) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def read(self) -> dict[str, object]:
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                assert self.proc.stderr
                raise AssertionError(f"el servidor murio: {self.proc.stderr.read()[:2000]}")
            if line.strip().startswith("{"):
                return json.loads(line)

    def call(self, id_: int, method: str, params: dict[str, object] | None = None) -> dict:
        self.send({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
        return self.read()["result"]  # type: ignore[index,return-value]

    def close(self) -> None:
        """Cierra los pipes ademas de matar el proceso.

        `Popen` con PIPE deja tres file objects abiertos; sin cerrarlos, Python emite
        ResourceWarning al recolectarlos y el gate de warnings (que es para esto) rompe
        el build. El leak seria nuestro, asi que se arregla, no se silencia.
        """
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        finally:
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                if stream is not None:
                    stream.close()


@pytest.fixture
def server() -> Iterator[Server]:
    s = Server()
    try:
        yield s
    finally:
        s.close()


def test_handshake_delivers_the_doctrine_to_the_client(server: Server) -> None:
    """`instructions` tiene que llegar por el cable, no solo existir en el objeto."""
    result = server.call(1, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    })
    assert result["serverInfo"]["name"] == "binance"  # type: ignore[index]
    instructions = result.get("instructions") or ""
    assert "kb://discipline" in instructions, "la doctrina no llega al cliente"
    assert "kb://research/no-edge" in instructions


def test_surface_is_complete_over_the_wire(server: Server) -> None:
    """25 tools / 8 recursos / 5 prompts, contados por el protocolo y no por introspeccion."""
    server.call(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "pytest", "version": "0"}})
    server.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    assert len(server.call(2, "tools/list")["tools"]) == 25       # type: ignore[index,arg-type]
    assert len(server.call(3, "resources/list")["resources"]) == 8  # type: ignore[index,arg-type]
    assert len(server.call(4, "prompts/list")["prompts"]) == 5    # type: ignore[index,arg-type]


def test_a_real_tool_call_round_trips(server: Server) -> None:
    """Contra la cuenta real: es el camino que rompia el bug del Decimal (`0E-8`)."""
    server.call(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "pytest", "version": "0"}})
    server.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    result = server.call(5, "tools/call", {"name": "binance_get_balance", "arguments": {}})
    assert not result.get("isError"), result
    rows = result["structuredContent"]["result"]  # type: ignore[index]
    assert rows, "la cuenta no devolvio balances"
    for row in rows:
        for field in ("free", "locked"):
            assert "E" not in row[field].upper(), f"{row['asset']}.{field} en notacion cientifica"
