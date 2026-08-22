"""Backends de confirmación multiplataforma (v1.2, spec Everywhere Edition).

Contrato de TODO backend — el mismo que ya cumple `dialog.ask_confirmation`:
- Firma `(text: str) -> bool`. El texto llega YA renderizado por executor desde el
  CanonicalOrder que se va a ejecutar (spec §4.3) — el backend lo TRANSPORTA, jamás
  compone texto propio ni recibe campos crudos.
- `False` ante todo lo que no sea un OK explícito: cancel, timeout, error, backend caído.
- Retorno en tiempo finito (<= CONFIRM_TIMEOUT_S): corre bajo `dialog_lock` en un hilo
  daemon — colgarse cuelga la cola de intents completa. No asumir main thread.
"""
from __future__ import annotations

import contextlib
import html
import http.server
import secrets
import select
import socket
import sys
import time
import webbrowser
from typing import TextIO

# Timeout único de confirmación (antes _DIALOG_TIMEOUT_S en dialog.py). < tool-call
# timeout del cliente (spec §2.1.9); timeout = deny en TODOS los backends.
CONFIRM_TIMEOUT_S = 45

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Binance MCP — confirm order</title>
<style>
 body {{ font: 16px/1.5 -apple-system, system-ui, sans-serif; max-width: 560px;
        margin: 8vh auto; padding: 0 20px; color: #111; }}
 pre  {{ background: #f6f6f6; border: 1px solid #ddd; border-radius: 8px;
        padding: 16px; white-space: pre-wrap; font-size: 15px; }}
 .warn {{ color: #b00; font-weight: 700; }}
 .row {{ display: flex; gap: 12px; margin-top: 20px; }}
 button {{ font-size: 16px; padding: 10px 22px; border-radius: 8px; cursor: pointer; }}
 .cancel  {{ background: #2563eb; color: #fff; border: 0; }}
 .confirm {{ background: #eee; border: 1px solid #bbb; }}
</style></head><body>
<h2>Binance MCP — confirm order</h2>
<p class="warn">Nothing executes unless you press Confirm. This page expires in {seconds}s.</p>
<pre>{text}</pre>
<div class="row">
 <form method="post" action="{base}/cancel"><button class="cancel" autofocus>Cancel</button></form>
 <form method="post" action="{base}/confirm"><button class="confirm">Confirm</button></form>
</div></body></html>"""

_ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def web_confirm(text: str) -> bool:
    """Confirmación por página local (cross-platform, sin deps).

    Servidor stdlib efímero SOLO en loopback, token one-shot en el path, POST-only para
    responder, valida el header Host (anti DNS-rebinding). Cancel es el botón con foco.
    Timeout ({CONFIRM_TIMEOUT_S}s) o cualquier error => deny."""
    token = secrets.token_urlsafe(24)
    base = f"/c/{token}"
    result: dict[str, bool] = {}
    deadline = time.monotonic() + CONFIRM_TIMEOUT_S

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # silencio: nada a stderr
            return

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            return host in _ALLOWED_HOSTS

        def do_GET(self) -> None:  # noqa: N802 — API de BaseHTTPRequestHandler
            if not self._host_ok() or self.path != base:
                self.send_error(404)
                return
            body = _PAGE.format(text=html.escape(text), base=base,
                                seconds=CONFIRM_TIMEOUT_S).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok() or self.path not in (f"{base}/confirm", f"{base}/cancel"):
                self.send_error(404)
                return
            result["ok"] = self.path.endswith("/confirm")
            verdict = "CONFIRMED — order sent." if result["ok"] else "Canceled. Nothing executed."
            body = f"<html><body><h2>{verdict}</h2>You can close this tab.</body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class _QuietServer(http.server.HTTPServer):
        # server_bind default llama socket.getfqdn() → reverse-DNS que puede tardar
        # SEGUNDOS (visto en runners macOS). Solo servimos loopback: nombre fijo.
        def server_bind(self) -> None:
            import socketserver
            socketserver.TCPServer.server_bind(self)
            self.server_name = "127.0.0.1"
            self.server_port = self.server_address[1]

    try:
        srv = _QuietServer(("127.0.0.1", 0), Handler)
    except OSError:
        return False
    try:
        srv.timeout = 1.0
        url = f"http://127.0.0.1:{srv.server_address[1]}{base}"
        print(f"[confirm] open to approve/deny (expires {CONFIRM_TIMEOUT_S}s): {url}",
              file=sys.stderr, flush=True)
        with contextlib.suppress(Exception):
            webbrowser.open(url)
        while "ok" not in result and time.monotonic() < deadline:
            srv.handle_request()  # respeta srv.timeout → re-chequea el deadline cada 1s
        return result.get("ok", False)
    finally:
        srv.server_close()


def tty_confirm(text: str, *, _stdin: TextIO | None = None) -> bool:
    """Confirmación por terminal (headless/SSH). POSIX: select sobre stdin con timeout.

    Exige teclear exactamente CONFIRM. Timeout, EOF, otra cosa, o Windows => deny
    (en Windows usar BINANCE_CONFIRM_MODE=web)."""
    stdin = _stdin if _stdin is not None else sys.stdin
    print(f"\n{text}\n", file=sys.stderr, flush=True)
    if not hasattr(select, "select") or sys.platform == "win32":
        print("[confirm] tty mode is POSIX-only; use BINANCE_CONFIRM_MODE=web",
              file=sys.stderr, flush=True)
        return False
    print(f"[confirm] type CONFIRM + Enter to execute (anything else denies; "
          f"{CONFIRM_TIMEOUT_S}s timeout): ", file=sys.stderr, flush=True)
    try:
        try:
            stdin.fileno()
            has_fd = True
        except Exception:  # noqa: BLE001 — stdin inyectado en tests (StringIO, sin fd)
            has_fd = False
        if has_fd:
            ready, _, _ = select.select([stdin], [], [], CONFIRM_TIMEOUT_S)
            if not ready:
                return False
        line = stdin.readline()
        return bool(line.strip() == "CONFIRM")
    except Exception:  # noqa: BLE001 — cualquier fallo del canal = deny (fail-closed)
        return False


def resolve_backend(mode: str):  # type: ignore[no-untyped-def]  # Callable[[str], bool]
    """Mapea el modo validado (config.load_confirm_mode) a su backend.

    `auto`: darwin → diálogo nativo; resto → web. Import de dialog DIFERIDO para no
    romper el patrón de monkeypatch de los tests."""
    if mode == "auto":
        mode = "macos" if sys.platform == "darwin" else "web"
    if mode == "macos":
        from kainext_binance_mcp_confirmer.dialog import ask_confirmation
        return ask_confirmation
    if mode == "web":
        return web_confirm
    return tty_confirm


# socket sólo se usa indirectamente vía http.server; el import explícito documenta
# que este módulo abre un puerto (loopback-only).
_ = socket
