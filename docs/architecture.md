# Architecture

Three processes and one library, with hard boundaries between them. The boundaries are the
product: they are what makes it safe to point a language model at a real-money account.

```
┌──────────────────┐   stdio    ┌─────────────────────┐  unix socket  ┌──────────────────┐
│   MCP client     │◀──────────▶│   MCP server        │◀─────────────▶│   confirmer      │
│ (Claude Code…)   │            │  READ key only      │  register /   │  TRADE key       │
│                  │            │  never executes     │  status only  │  executes on a   │
└──────────────────┘            └─────────────────────┘               │  human click     │
                                          │ lazy import               └──────────────────┘
                                          ▼
                                ┌─────────────────────┐
                                │  futures/ (research)│  NO keys · NO tools · offline
                                │  public archives    │  never imported at server start
                                └─────────────────────┘
```

## Why the model never holds a trade key

The server process loads only `BINANCE_READ_*`. The confirmer — a separate process the
operator launches themselves — is the only holder of `BINANCE_TRADE_*` and the only code
that places orders. Over the socket travels a `CanonicalOrder` and nothing else: the
confirmer renders the confirmation text **from that object**, so a compromised model cannot
change what the human sees. The wire protocol has no `execute` verb at all (`ipc.py`:
`_ALLOWED_TYPES = {"register", "status"}`).

To execute one order an attacker needs both the trade key, isolated in another process, and
a physical click. The model has neither.

## Why `futures/` is separate

The research engine has no business touching credentials, and the guarantee above only
holds if that stays true. So:

- It reads **public archives** (`data.binance.vision`) over plain HTTP, with no API key.
- It exposes **no MCP tools** — nothing about it reaches the model.
- The server **lazy-imports** it, so a `uvx` install without the `[research]` extra starts
  normally even though `numpy` is absent.
- `mypy --strict` and the ≥90% coverage gate cover it like the rest of `src/`. The
  walk-forward lives in `futures/research.py` rather than `examples/` precisely because
  mypy does not check `examples/` — which is how a duplicated, untyped, untested second
  backtest engine got in there once already.

## The data layer, and three traps that corrupt silently

Downloading five years of ~986 symbols over REST is not viable (1000 candles per call); the
monthly archives are ~120 MB for the whole universe at 1d. But the archives have three
traps, all verified against real files:

1. **The CSV header changed between eras.** Files from 2020 have **no header**; from 2022-06
   onward they do. Fixing `header=0` eats the first candle of every old month; fixing
   `header=None` injects a text row into every modern one. The parser sniffs.
2. **The current month is missing.** Binance publishes a monthly archive on the first Monday
   of the following month, so there is up to a five-week hole that must be filled from the
   daily archives. Without it the panel silently lags and nothing complains.
3. **Today's candle is incomplete.** It is still forming until the UTC close, and a partial
   candle in a momentum ranking is lookahead in disguise. The panel ends yesterday, on
   purpose — which is also why no REST call is needed for closed daily bars.

A fourth was found by running it against the real archive rather than a fixture: the
archives come in whole months, so asking for data up to the 5th returned the entire month.
A backtest receiving candles **after** its window is lookahead even if nobody looks at them
deliberately. The panel is clipped to the requested range.

Funding rates carry a `funding_interval_hours` **column** — Binance models the interval as
variable, so it is read from the data rather than hardcoded to 8h.

## The universe, and survivorship bias

527 USDT perpetuals trade today; the archive holds 986 symbols. Ranking only the survivors
asks the past a question using the future's answer. Membership is derived **from the data**:
a symbol belongs to the universe on day `t` if it has a closed candle on `t`. Absence
encodes both listing and delisting, with no separate registry.

Two filters, both causal: minimum history (ranking 90-day momentum on a five-day-old symbol
is noise) and minimum liquidity (without it the winning decile fills with dead books whose
"return" is spread noise).

Symbols carrying a denomination multiplier (`1000PEPE`, `1000000BOB` — 13 of the 527 live)
are treated as distinct instruments and **never chained** to their predecessor: a relisting
at a different multiplier produces a ×1000 price jump that would appear as a +99,900% return
and dominate any momentum ranking.
