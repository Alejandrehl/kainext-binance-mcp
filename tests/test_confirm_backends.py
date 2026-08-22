"""Backends de confirmación v1.2: contrato (text)->bool, default deny, timeout=deny."""
from __future__ import annotations

import io
import threading
import urllib.error
import urllib.request

import pytest

import kainext_binance_mcp_confirmer.confirm_backends as cb
from kainext_binance_mcp.config import ConfigError, load_confirm_mode

# --- load_confirm_mode ---

def test_load_confirm_mode_default_and_valid() -> None:
    assert load_confirm_mode({}) == "auto"
    for m in ("auto", "macos", "web", "tty"):
        assert load_confirm_mode({"BINANCE_CONFIRM_MODE": m}) == m
    with pytest.raises(ConfigError, match="BINANCE_CONFIRM_MODE"):
        load_confirm_mode({"BINANCE_CONFIRM_MODE": "gui"})


def test_resolve_backend_mapping(monkeypatch) -> None:
    assert cb.resolve_backend("web") is cb.web_confirm
    assert cb.resolve_backend("tty") is cb.tty_confirm
    monkeypatch.setattr(cb.sys, "platform", "linux")
    assert cb.resolve_backend("auto") is cb.web_confirm
    monkeypatch.setattr(cb.sys, "platform", "darwin")
    from kainext_binance_mcp_confirmer.dialog import ask_confirmation
    assert cb.resolve_backend("auto") is ask_confirmation


# --- web backend (server real en hilo, requests locales) ---

def _run_web(text: str, actor) -> bool:
    """Corre web_confirm en un hilo y deja que `actor(url)` interactúe."""
    result: dict[str, bool] = {}
    url_box: dict[str, str] = {}

    real_open = cb.webbrowser.open

    def capture(url: str) -> bool:
        url_box["url"] = url
        return True

    cb.webbrowser.open = capture  # type: ignore[assignment]
    try:
        t = threading.Thread(target=lambda: result.update(ok=cb.web_confirm(text)),
                             daemon=True)
        t.start()
        for _ in range(200):
            if "url" in url_box:
                break
            import time
            time.sleep(0.01)
        actor(url_box["url"])
        t.join(timeout=10)
        assert not t.is_alive(), "web_confirm no retornó"
        return result["ok"]
    finally:
        cb.webbrowser.open = real_open  # type: ignore[assignment]


def test_web_confirm_confirm_and_page_shows_text() -> None:
    def actor(url: str) -> None:
        page = urllib.request.urlopen(url, timeout=5).read().decode()
        assert "BUY LIMIT  BTCUSDT &lt;test&gt;" in page  # texto ESCAPADO
        assert "autofocus" in page.split("Cancel")[0].rsplit("<", 1)[-1] or "cancel" in page
        req = urllib.request.Request(url + "/confirm", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=5)

    assert _run_web("BUY LIMIT  BTCUSDT <test>", actor) is True


def test_web_confirm_cancel_and_bad_token() -> None:
    def actor(url: str) -> None:
        # token inválido → 404, no cuenta como respuesta
        base = url.rsplit("/c/", 1)[0]
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/c/WRONGTOKEN", timeout=5)
        req = urllib.request.Request(url + "/cancel", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=5)

    assert _run_web("x", actor) is False


def test_web_confirm_get_cannot_approve() -> None:
    """POST-only: un GET a /confirm (prefetch de browser) NO aprueba."""
    def actor(url: str) -> None:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(url + "/confirm", timeout=5)  # GET → 404
        req = urllib.request.Request(url + "/cancel", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=5)

    assert _run_web("x", actor) is False


def test_web_confirm_timeout_denies(monkeypatch) -> None:
    monkeypatch.setattr(cb, "CONFIRM_TIMEOUT_S", 1)
    def actor(url: str) -> None:  # no responde nada
        pass
    assert _run_web("x", actor) is False


def test_web_confirm_rejects_foreign_host() -> None:
    """Anti DNS-rebinding: Host ajeno → 404 aunque el token sea correcto."""
    def actor(url: str) -> None:
        req = urllib.request.Request(url + "/confirm", data=b"", method="POST",
                                     headers={"Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(req, timeout=5)
        req2 = urllib.request.Request(url + "/cancel", data=b"", method="POST")
        urllib.request.urlopen(req2, timeout=5)

    assert _run_web("x", actor) is False


# --- tty backend ---

def test_tty_confirm_exact_word_confirms(monkeypatch) -> None:
    monkeypatch.setattr(cb, "CONFIRM_TIMEOUT_S", 2)
    assert cb.tty_confirm("t", _stdin=io.StringIO("CONFIRM\n")) is True
    assert cb.tty_confirm("t", _stdin=io.StringIO("confirm\n")) is False
    assert cb.tty_confirm("t", _stdin=io.StringIO("yes\n")) is False
    assert cb.tty_confirm("t", _stdin=io.StringIO("")) is False  # EOF => deny
