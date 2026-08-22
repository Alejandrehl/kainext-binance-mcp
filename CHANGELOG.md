# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [1.2.0] — 2026-08-22 — "Everywhere Edition"

Execution on every OS, push notifications without keys, and backtests of the strategies
the doctrine actually recommends.

### Added
- **Cross-platform confirmation backends** (`BINANCE_CONFIRM_MODE`: auto|macos|web|tty).
  `web`: ephemeral localhost page (one-shot token, POST-only, Host-validated, Cancel
  focused, 45s timeout = deny). `tty`: exact `CONFIRM` word on POSIX terminals. All
  invariants preserved (text rendered from the canonical order, default deny).
- **`kainext-binance-mcp-watch`**: a keyless watchdog process — price / completed daily
  close / funding / Fear & Greed triggers from public endpoints, crossing-based
  anti-spam with persisted state, desktop notification + optional https webhook.
  It notifies and can execute nothing, by construction.
- **`binance_backtest_dca`** and **`binance_backtest_harvest`** (23 → 25 tools): honest
  historical simulations of mechanical DCA (with lump-sum comparison and max drawdown)
  and pre-committed harvest grids (vs pure hold). `fetch_klines_range` paginates beyond
  the 1000-candle API cap (~9 years of daily history).
- `server.json` + listing in the official MCP Registry (`io.github.alejandrehl/*`).
- Docs: supply-chain section (trusted publishing + Sigstore attestations — active since
  v1.0.0, now documented), confirmation backends, watch mode.

### Changed
- Dependency batch (Dependabot): pandas 3.0.5, mypy 2.3.1, feedparser 6.0.14,
  pytest-cov 7.1.0, actions/checkout v7, setup-uv v7. pytest-asyncio deferred to the
  SDK 2.0 release.

## [1.1.0] — 2026-08-22 — "Analyst Edition"

The MCP becomes a complete, honest crypto analysis consultant: data an analyst actually
watches, analytical frameworks as tools, and — the differentiator — the consultant's
knowledge shipped through MCP prompts and resources.

### Added
- **Knowledge layer (layer 7)**: 8 `kb://` resources (investment discipline, the no-edge
  walk-forward research, a source registry with bias annotations, news/cycle/token-value
  frameworks, a versioned macro calendar, a glossary with interpretive readings) and
  5 prompt playbooks (`portfolio_review`, `asset_thesis`, `market_briefing`, `risk_check`,
  `dca_plan`). Server `instructions` wire the knowledge so clients read the doctrine
  before any investment analysis. All English; a test guards that no personal data ships.
- **Analyst data (layer 5)**: `binance_get_derivatives` (public futures funding/OI/mark —
  no signature, no extra key permissions; synthetic on testnet) and
  `binance_get_market_structure` (Fear & Greed + week series, BTC dominance, total market
  cap, BTC ATH/drawdown, mempool fees & hashrate; 5s per-source timeout, >=300s TTL cache,
  per-source degradation with notes).
- **Analytical frameworks (layer 6)**: `binance_analyze_cycle` (Mayer Multiple, ATH
  drawdown, halving distance), `binance_analyze_portfolio` (valuation, concentration,
  per-asset PNL and parametric NET break-even — cost basis/tax/spread are always user
  parameters), `binance_assess_risk` (realized vol 30/90d, max drawdown, BTC correlation).
- 3 new RSS sources: The Block, Decrypt, Federal Reserve press (primary macro).
- 18 → 23 tools.

### Changed (behavior)
- `binance_get_news` without `sources=` now queries 5 sources instead of 2 (The Block,
  Decrypt and Fed press join CoinDesk and crypto.news). Fed items score neutral sentiment
  (the lexicon is crypto-specific) — intended.
- `requests==2.34.2` promoted from transitive to declared dependency.

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
