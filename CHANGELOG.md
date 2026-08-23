# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

The package stops being spot-only: it now also ships an **offline USD-M futures research
engine**, and the doctrine that governs it changed accordingly.

### Added

- **Futures research engine** (`kainext_binance_mcp.futures`, behind the new `[research]`
  extra). Keyless and offline: it reads Binance's public archives with no API key, exposes
  **no MCP tools**, and the server never imports it — a `uvx` install without the extra
  starts exactly as before.
  - `data.py` — historical panel from the monthly and daily archives, SHA256-verified,
    resumable, cached outside iCloud. Handles three traps that corrupt silently: the CSV
    header changed between eras (2020 files have none), the current month is missing from
    the monthly archives, and today's candle is incomplete — lookahead in disguise.
    `funding_interval_hours` is read from the data, not hardcoded to 8h.
  - `universe.py` — point-in-time universe free of survivorship bias. 527 USDT perpetuals
    trade today but the archive holds 986 symbols; **306 delisted USDT perps** are
    recoverable. Denomination-multiplier symbols (`1000PEPE` and 12 others) are never
    chained to their predecessor: a relisting would show as a +99,900% return and dominate
    any momentum ranking.
- **`tests/test_consistency.py`** — anti-drift gate. Fails the build when the docs stop
  describing the product: version lockstep across `pyproject`/`server.json`/`CHANGELOG`,
  README tool counts (total **and** per section), declared scope, and credentials in
  `.mcp.json`.
- **`tests/integration/test_mcp_protocol.py`** — real MCP handshake over stdio. Nothing
  tested the product as a client sees it, which is exactly how the `instructions` trap below
  could have shipped.
- **`CLAUDE.md`, `ROADMAP.md`, `docs/architecture.md`, `docs/research/README.md`.**
- **`.mcp.json` is now versioned**, declaring only remote OAuth servers. The blanket
  gitignore was hope; the gate is verification.
- **`funding_events`** on `DerivativesSnapshot` — funding history with its timestamps.
  Additive: `funding_history` is unchanged for existing consumers.

### Changed (behavior)

- **The doctrine now has two regimes that never mix** (`kb://discipline`). Rules 1-6 govern
  the long-term spot portfolio and are unchanged. New rule 7 governs systematic research,
  where leverage is admissible **only** after clearing every condition: out-of-sample
  validation corrected for multiple testing, rules written before execution, volatility
  targeting, a drawdown circuit breaker, segregated capital, and a full decision record.
  Discretionary directional leverage remains forbidden, explicitly. **Order execution is
  still spot-only and human-gated.** `_INSTRUCTIONS` ships this to every MCP session.
- **`mcp[cli]` 1.29.0 → 2.0.0.** `mcp.server.fastmcp.FastMCP` is gone; it is now
  `mcp.server.mcpserver.MCPServer`. The trap: the second positional argument changed from
  `instructions` to `title`, so a naive bump left `instructions=None` and silently stopped
  injecting the doctrine into every session while all tests still passed.
- `ruff` 0.7.2 → 0.16.3 (pre-commit aligned to the same pin); required PEP 695 generics in
  `run_guarded`. `pytest` 8.3.3 → 9.1.1 **with** `pytest-asyncio` 0.24.0 → 1.4.0 — bumping
  pytest alone was unresolvable.
- Zero-warnings gate: `filterwarnings = ["error"]`. Every ignore names its upstream cause.

### Fixed

- **`Decimal` never serialises as scientific notation.** Binance returns `"0.00000000"` for
  a zero `locked`; `str(Decimal("0.00000000"))` is `"0E-8"`, which the auto-generated output
  schema rejects — so `binance_get_balance` failed on a normal wallet. This affected **all
  47 `Decimal` fields**, not one tool. Fixed once, as a policy, in `models.py`.
- Orphan `asyncio` event loop from `python-binance` broke only the py3.12 CI cells: on 3.12
  `get_event_loop()` creates a loop nobody closes; on 3.13 it does not. Non-deterministic,
  so a green local run proved nothing.

### Internal

- One backtest engine. `examples/walk_forward.py` had a hand-written second implementation
  of `backtest.simulate`; a differential test proved they agreed exactly — so the published
  research stands — and `sim_window` now delegates. Measured cost: ~2 s over the full
  walk-forward.
- Removed `scripts/smoke_dialog_testnet.py`: a near-identical duplicate of the `examples/`
  copy, referenced by nothing, unlinted by CI, and touching the trade key path.
- Documentation caught up with the product: README scope, section counts (declared 23 while
  the header said 25), the doctrine row that still said "never leverage", the macOS-only
  execution claim (false since v1.2), stale `@v1.0.0` install pins, `CONTRIBUTING`'s ruff
  command that did not match CI, and the `server.json` registry listing.

## [1.2.1] — 2026-08-22

- MCP Registry ownership marker (`mcp-name`) in the README (required by the registry's
  PyPI ownership validation). No functional changes.

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
