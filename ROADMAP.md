# Roadmap — the quant programme

Three phases. This file states the **measured** state, not an estimate: a roadmap that
doesn't say how much is actually left is marketing.

The MCP spot server is a finished, shipped product; it evolves through maintenance, not
through this roadmap. What follows is the futures research programme.

**Last measured:** `23-08-2026`.

---

## Phase 0 — the engine that kills strategies · **2 of 8 modules**

The deliverable is not a strategy. It is the machine that tells you, honestly, whether a
strategy has an edge. If the first hypothesis dies in walk-forward, the phase succeeded.

| Module | State | What it does |
|---|---|---|
| `futures/data.py` | ✅ **done** | Historical panel from Binance's public archives. 15 tests, verified end-to-end against the real archive |
| `futures/universe.py` | ✅ **done** | Point-in-time universe, survivorship-bias free. 14 tests; reproduces 986 symbols / 527 live / 306 delisted / 13 multiplier-renamed exactly |
| `futures/costs.py` | ⬜ **pending** | Commission as a **required** parameter with no silent default, real funding accrual, slippage that is never zero |
| `futures/portfolio.py` | ⬜ **pending** | Multi-symbol long/short, notional vs margin, volatility targeting, funding accrual, liquidation proximity assertion |
| `futures/stats.py` | ⬜ **pending** | Sharpe, Sortino, max drawdown, turnover + **Deflated Sharpe Ratio** + **PBO (CSCV)**. `math.erf` only — no `scipy` |
| `futures/research.py` | ⬜ **pending** | The walk-forward, typed and tested (not in `examples/`, which mypy does not check) |
| `futures/db/` | ⬜ **pending** | Postgres on Railway: schema, migrations with advisory lock + checksum, `COPY` writes |
| `futures/strategies/` | ⬜ **pending** | The hypothesis implementations |

**Two things cannot be verified until a futures API key exists** (Phase 2), and every
Phase 0 result is provisional until then: the account's **real commission** and the
**maintenance-margin tiers**. Both sit behind signed endpoints.

### Why the database is not optional

`stats.py` cannot compute DSR without the Sharpe of **every** trial, and cannot compute PBO
without the full trial × period return matrix. A harness that only reports the winner makes
both corrections impossible to calculate afterwards without re-running everything. The
store is a requirement, not a nicety — and it also enables the table that matters most,
`live_vs_model`: modelled return vs realised, decomposed into fee / slippage / funding.
It is how you find out your cost model is lying.

---

## Phase 1 — the hypotheses

Every hypothesis carries the **same gate, written before the run**:

> OOS return net of costs > 0 in absolute terms · Sharpe > 1.0 · **DSR > 0** · **PBO < 0.5**
> · beats buy-and-hold in > 50% of windows · ≥ 50 OOS trades

Fixing the criterion beforehand is what makes the result mean anything.

| Hypothesis | State | Note |
|---|---|---|
| **Grid / volatility selling** | 🔬 first look done | On SOL 1h: 2 SOL → **3.99 SOL** in 2025 (14 cycles, +99% vs holding). Also **−75% vs holding** in the 2023-26 uptrend, and **zero trades** in a pure downtrend. Short volatility: paid for oscillation, punished by trend. One asset, three windows, generous fills — **not a validated edge** |
| **Cross-sectional momentum** | ⬜ pending | Rank the perp universe by k-period return, long top decile / short bottom. The factor with the most academic support in crypto, and the one that best exploits breadth |
| **Funding / basis carry** | ⬜ pending | Long spot + short perp, harvesting funding. The only one that pays without a predictive edge. Low return, capital-bound |
| **Liquidation cascades** | 🚫 blocked | **No public history exists** (verified: `liquidationSnapshot` is absent from the archives). Requires collecting via websocket for months before it can be backtested |

Execution realism is not a detail: `minNotional` is **not uniform** (BTCUSDT requires 50
USDT, most require 5), `stepSize` forces integer quantities on some symbols, 13 live symbols
carry denomination multipliers that must never be chained to their predecessor, and a symbol
that delists mid-position must be force-closed, not silently dropped.

---

## Phase 2 — live execution

Not started, and deliberately gated behind a surviving hypothesis.

- A futures API key class, with `enableWithdrawals` blocked permanently.
- A bot process separate from the MCP server and the confirmer, deployed on Railway,
  reaching Postgres over the private network.
- State reconciliation after a crash, order idempotency, kill switch, drawdown breaker.
- Capital: the strategy is only half the problem. Matching the operator's second income
  needs **$25-45k of risk capital**, which comes from billing, not from trading.

### The security decision that has to be made with open eyes

Introducing futures execution makes parts of `SECURITY.md` false, and that is a decision,
not an oversight:

- *"the confirmer aborts if the trade key has futures permissions"* — inverted by definition.
- *"to execute an order an attacker needs the trade key **and** your physical click"* — only
  survives if the futures key is confirmer-isolated too.
- **Liquidation is an irreversible, funds-moving event with no human in the loop, by
  construction.** No confirmer design restores that guarantee.

---

## Done and shipped (`23-08-2026`)

Fixed a production bug where every `Decimal` field could serialise as scientific notation
and fail output validation · unified the two backtest engines behind one implementation ·
made the suite warning-clean with a gate that fails on any new warning · added the
anti-drift consistency gate · rewrote the doctrine into two regimes · built the data and
universe layers · upgraded to `mcp` 2.0 / `ruff` 0.16.3 / `pytest` 9.1.1.
