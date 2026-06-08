# Contributing

Thanks for your interest in `kainext-binance-mcp`. This is a small, security-sensitive
codebase that handles real money, so the bar for changes is deliberately high.

## Ground rules

- **No tech debt.** No `TODO`/`FIXME`, no placeholders, no "good enough for now".
- **Security first.** Any change that touches the read/trade key boundary, the confirmer, the
  IPC channel, or the order-execution path gets extra scrutiny. When in doubt, open an issue
  first.
- **Never commit secrets.** `.env` and `.mcp.json` are git-ignored. Keep credentials in your
  shell, never in the repo.

## Development setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone git@github.com:Alejandrehl/kainext-binance-mcp.git
cd kainext-binance-mcp
uv venv --python 3.12
uv pip install -e ".[dev]"
```

## Quality gates (must pass before a PR is mergeable)

These run in CI on every push and pull request, and mirror what you should run locally:

```bash
uv run ruff check src/     # lint
uv run mypy                # strict type checking
uv run pytest -q           # tests + coverage (gate: --cov-fail-under=90, lives in pyproject)
```

The unit suite runs fully offline. Integration tests (`-m integration`) hit Binance testnet
and **skip cleanly** when no testnet keys are exported, so you don't need credentials to
contribute to most of the code.

## Pull requests

- Keep PRs focused and small.
- Add or update tests for any behavior change — coverage must stay at or above the gate.
- Update the README/docs when you change observable behavior (tools, env vars, flow).
- Use clear, [Conventional Commits](https://www.conventionalcommits.org/) style messages.
