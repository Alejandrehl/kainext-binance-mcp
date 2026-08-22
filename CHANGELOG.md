# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-08-22

First stable release. 18 tools, two-process security model (read-key MCP server proposes;
a separate human-gated confirmer holding the trade key is the only thing that can execute).

### Added
- `examples/` (walk-forward, strategy matrix, market snapshot, cycle verification, testnet
  dialog smoke) and `docs/research/` with the out-of-sample results: **no robust edge in any
  of 36 configurations** — the reason signals ship as context, not alpha.
- `last_n` on `binance_get_klines` (mirror of `compute_indicators`) to keep model context small.
- Symbol validation everywhere (`^[A-Z0-9]{2,20}$`), shared with `CanonicalOrder` — the trust
  boundary that reaches the AppleScript dialog.
- CI matrix (ubuntu + macOS × Python 3.12/3.13), `pip-audit` job, CodeQL, Dependabot,
  pre-commit (ruff), issue/PR templates.
- PyPI publishing via trusted publishing (`release.yml` on `v*` tags).
- Legal disclaimer and research section in the README.

### Changed (behavior)
- **Unified error contract for read-only tools**: any exception now surfaces as a mapped,
  secret-scrubbed `ToolExecutionError` instead of a raw client exception (three different
  error behaviors previously coexisted). Write tools keep `OrderProposal(error=ToolError)`.
- **Confirmer dialog is now English** (`Cancel` / `Confirm`, `⚠️ REAL MONEY (MAINNET)`), and
  the osascript result matcher was updated in the same change.
- All user-facing strings (tool descriptions, validation/config/guard/IPC errors) are English.
- `binance_spot_order_propose` / `binance_cancel_order_propose` return
  `ToolError("ipc_unavailable")` when the confirmer is down (previously an uncaught exception).
- `binance_get_order_history` bounds `limit` to 1–1000.
- Backtest strategy label: `composite_technical_signal` (was Spanish).

### Fixed
- Confirmer IPC: a local client that connects and disconnects without completing a request
  no longer kills the serve loop (previously a `BrokenPipeError` took the whole confirmer
  down — a local denial-of-service).
- Confirmer: a failing authoritative re-estimate (network/symbol) now marks the intent
  `failed` immediately instead of killing the worker thread and leaving it `pending` for the
  300 s TTL.
- AppleScript dialog escaping now escapes backslashes and quotes (previously quotes were
  replaced by apostrophes).
- Layer-3 integration test no longer hits live RSS feeds in CI (opt-in via
  `RUN_NETWORK_TESTS=1`).

### Internal
- `runtime.py`: single home for `bootstrap`, `make_estimator`, `SOCKET_PATH` (were duplicated
  across server and confirmer); single settings loader; `NOT_CANCELABLE` and `client_secrets`
  deduped; `signals/common.py` for shared indicator knobs/helpers (~130 duplicated lines removed).
- Real ruff gate (`E,F,I,B,UP,SIM,BLE` + enforced line length) across `src/`, `tests/`,
  `examples/`; documented per-file-ignores. `ruff format` deliberately not adopted.
- `python-binance` 1.0.36 → 1.0.37; **`mcp` 1.16.0 → 1.29.0** (with `pydantic` 2.11.7 → 2.13.4, required by mcp's universal resolution) — `pip-audit` flagged three
  PYSEC advisories on 1.16.0 (PYSEC-2026-1617/3482/3483, all fixed by 1.28.1); staying on the
  1.x line. Migrating to MCP SDK 2.x is scheduled as its own release (see Roadmap).
- Personal one-off scripts removed from the repository (moved to private storage); the public
  research scripts live on as `examples/`.
