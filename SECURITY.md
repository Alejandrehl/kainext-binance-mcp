# Security Policy

This project lets an AI assistant interact with a **real-money** exchange account.
Security is the headline feature, not an afterthought. This document explains the
threat model, the guarantees the design provides, and how to report a problem.

## Threat model

The core assumption is adversarial: **treat the language model as untrusted.** A model
can be confused, prompt-injected, or simply wrong. The architecture is built so that even
a fully-compromised model **cannot move funds on its own**.

### What the design guarantees

- **The model never holds a trade key.** The MCP server runs with a **read-only** API key
  (`BINANCE_READ_*`). It can read balances/markets and *propose* orders, but it has no
  credential capable of executing a trade.
- **Execution lives in a separate process.** The confirmer
  (`kainext-binance-mcp-confirmer`) is the *only* component with the **trade** key
  (`BINANCE_TRADE_*`), and you launch it yourself in your own shell. The trade key is never
  passed to the MCP server or to the AI client's environment.
- **Human-in-the-loop for every irreversible action.** No order or cancellation executes
  without a **physical click** on a native confirmation dialog that shows the *exact*
  canonical fields about to be sent. The default button is **Cancel**.
- **Re-validation at the boundary.** The confirmer re-validates every proposal against the
  live symbol filters before execution — it does not trust the fields it received.
- **Least privilege, enforced in code.** On mainnet the server **aborts at startup** if its
  read key can trade, and the confirmer **aborts at startup** if the trade key has
  withdrawals / universal-transfer / internal-transfer / margin / futures permissions, or if
  IP whitelisting is off. Withdrawals and transfers are out of scope permanently — no key
  used by this project enables them.

To execute a single order, an attacker would need **both** the trade key (isolated in the
confirmer process) **and** your physical click. The model has neither.

## Operator responsibilities

- **Never put the trade key in `.mcp.json`** or in any environment the AI client inherits.
  It belongs only in the shell where you launch the confirmer.
- **Create two distinct API keys** with the minimum permissions described in the README
  (read-only for the server; trade-only + IP whitelist for the confirmer).
- **Start on testnet.** Verify the full flow with fake money before touching mainnet.
- **Keep secrets out of git.** `.env` and `.mcp.json` are git-ignored; keep them that way.

## Reporting a vulnerability

If you find a security issue, **please do not open a public issue.** Report it privately:

- GitHub: open a [private security advisory](https://github.com/Alejandrehl/kainext-binance-mcp/security/advisories/new)
- Or email the maintainer (see the GitHub profile of [@Alejandrehl](https://github.com/Alejandrehl)).

You'll get an acknowledgement as soon as possible. Please include reproduction steps and the
potential impact. Thank you for helping keep users' funds safe.

## Supported versions

This project is pre-1.0 and evolving. Security fixes target the latest `main`.

## Note on public futures endpoints (v1.1+)

The analyst tools call PUBLIC Binance futures endpoints (`fapi.binance.com`: funding
rate, open interest, mark price). These are unsigned — the API secret is never used —
but python-binance attaches the read key as a header on every request, so the read key
is transmitted to `fapi.binance.com` (same operator as the spot API; the endpoints
ignore it). No futures permissions are required or checked, and the startup guard still
rejects read keys that can trade.

## Supply chain (v1.0+)

Releases are built and published by `release.yml` via PyPI **trusted publishing** (OIDC,
no long-lived tokens) and carry **Sigstore attestations** tied to the workflow identity —
verify any distribution file at `https://pypi.org/integrity/`. Dependencies are pinned
exactly and audited in CI (`pip-audit`); CodeQL runs on every push.

## The watch process (v1.2)

`kainext-binance-mcp-watch` holds **no credentials** and talks only to public endpoints;
it can notify but has no code path that could place, cancel, or propose an order.
