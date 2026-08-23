# Research: is there a technical edge? (Spoiler: we could not find one)

Most "AI trading" products imply their signals make money. We tested ours properly and
publish the result, because an honest consultant leads with its own limitations.

## What we tested
- 4 pairs (BTC, ETH, SOL, BNB vs USDT) × 3 timeframes (1h, 4h, 1d) × 3 strategies
  (EMA cross, RSI threshold, and this server's composite technical signal) = 36 cells.
- ~51,000 real mainnet candles. Walk-forward validation: parameters chosen ONLY on
  training windows, measured on unseen test windows (17-30 windows per cell), with
  triple anti-lookahead controls and a market-regime filter.
- Commission modeled at 0.1% per side; **no slippage modeled — reality is worse.**

## What we found
- **0 of 36 configurations showed a robust out-of-sample edge** over simply buying and
  holding.
- In-sample "edges" existed — and evaporated out-of-sample. They were overfitting.
- Most apparent wins were really "losing less in downtrends", which cash also achieves.
- In strong uptrends, trend-cutting strategies destroyed returns versus holding.

## What this means for you
1. Signals from this server (`binance_generate_signal`, `binance_scan_signals`) are
   **context, not alpha**: a transparent summary of trend/momentum/volatility/sentiment
   with every factor's contribution exposed. Use them to structure attention, never as
   buy/sell instructions.
2. If a vendor claims a profitable simple technical strategy, ask for their walk-forward,
   out-of-sample results net of costs. In-sample backtests are marketing.
3. The reliable levers are behavioral: position sizing, DCA, harvesting into strength,
   and not losing more (`kb://discipline`).

## The same standard applies to everything we test next

This result is why the bar moved up rather than down. Any future strategy — including
leveraged and market-neutral ones — has to clear a *stricter* gate than these 36 did:
walk-forward on unseen windows, net of fees, funding and slippage, plus a correction for
multiple testing (Deflated Sharpe Ratio, probability of backtest overfitting). Those
corrections exist because the more configurations you try, the more certain you are to
find something that looks like alpha and is **not alpha**.

Results get published here whether they work or not. A research programme that only
reports its winners is marketing with extra steps.

Reproducible scripts and full result tables live in the repository:
`docs/research/walk_forward_results.md`, `docs/research/experiment_results_matrix.md`,
`examples/walk_forward.py`, `examples/experiment_matrix.py`.
