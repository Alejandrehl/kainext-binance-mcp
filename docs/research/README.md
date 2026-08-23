# Research index

What has been tested, what died, and what is still open. Results are published whether they
work or not — a research programme that only reports its winners is marketing with extra
steps.

> **Language note:** the two write-ups below are in Spanish; the rest of the repo's
> documentation is in English. They are published results and are left as they were written.

## Completed

| Study | Verdict |
|---|---|
| [`walk_forward_results.md`](walk_forward_results.md) | **0 of 36 configurations** showed a robust out-of-sample edge. EMA cross, RSI threshold and the composite signal, over 4 pairs × 3 timeframes, ~51,000 real candles, walk-forward with triple anti-lookahead. In-sample "edges" were overfitting |
| [`experiment_results_matrix.md`](experiment_results_matrix.md) | The in-sample matrix that the walk-forward above later falsified. Kept as the illustration of why in-sample backtests are marketing |

## Open

Nothing has cleared the bar yet. The hypotheses queued for the futures engine, and the gate
each must pass before it means anything, are in [`../../ROADMAP.md`](../../ROADMAP.md).

One first look exists and is **not** a validated result: a grid / volatility-selling rule on
SOL turned 2 SOL into 3.99 SOL across 2025 (14 cycles), and lost 75% against simply holding
during the 2023-26 uptrend. One asset, three windows, generous fill assumptions, no
correction for multiple testing. It is a reason to test properly, not a finding.

## The standard

Every future study must clear, at minimum: out-of-sample walk-forward on unseen windows,
net of fees, funding and slippage; a **Deflated Sharpe Ratio above zero**; and a **low
probability of backtest overfitting**. Those corrections exist because the more
configurations you try, the more certain you are to find something that looks like alpha
and is not.
