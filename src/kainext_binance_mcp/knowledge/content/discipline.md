# Investment discipline — the rules that actually work

This is the operating doctrine of this MCP. It is deliberately boring: our own
out-of-sample research (`kb://research/no-edge`) showed that simple technical strategies
do not beat holding, so the edge available to a retail investor is **behavioral**, not
technical. Every recommendation this consultant produces must be consistent with these rules.

## 1. Time in market beats timing the market
- Dollar-cost averaging (DCA) — a fixed amount on a fixed day, unconditionally — removes
  the two decisions retail investors reliably get wrong: when to enter and when to re-enter.
- A "conditional DCA" ("only buy on dips") is market timing wearing a disguise. If you had
  a timing edge you could prove, you would not need the DCA.
- The evidence for this position is in this very server: 36 strategy configurations,
  walk-forward validated on ~51,000 real candles, **zero** robust out-of-sample edges.

## 2. Position sizing is the only risk control that always works
- Never hold more crypto than you can watch fall 75% without selling. That number is not
  rhetorical: BTC has drawn down 77-84% in past cycles and ~50% in the mildest one.
- Concentration limits matter more than picking winners. Bitcoin has survived every cycle;
  most altcoins from past cycles never recovered their highs. High-beta positions
  (alts, small caps) belong in the small end of the portfolio, sized so their total loss
  is acceptable.
- Rebalancing into strength (harvesting) beats averaging down into a thesis that is breaking.

## 3. Never use leverage
- Funding costs bleed you in sideways markets; liquidations convert temporary drawdowns
  into permanent losses. The exchange's liquidation engine is the counterparty that never
  sleeps. Spot only. This server does not expose margin or futures trading by design.

## 4. Decide in cold blood, execute mechanically
- Every sell level, stop, or rotation rule must be **written before** the market approaches
  it, with the reasoning attached. Decisions made while watching a green or red candle are
  the ones you will regret.
- Harvest grids: pre-commit to selling fixed percentages at fixed levels on the way up.
  Never cancel or raise a resting harvest order during a rally — that impulse is the same
  FOMO that caused the losses you are trying to recover.
- Pre-commit to the downside too: write down the price at which you would NOT sell
  ("this drawdown is part of the plan") and the falsifiable condition under which the
  thesis is actually broken.

## 5. Your real break-even is higher than your entry price
- Taxes on gains, exchange/cash-out spreads, and your local currency's movement against
  USD all raise the price at which you are actually whole. Compute the **net** break-even
  before celebrating a recovery — `binance_analyze_portfolio` accepts `tax_rate` and
  `cashout_spread` parameters for exactly this.
- Selling in tranches spreads tax events and removes the need to time a single exit.

## 6. Process over outcome
- A good decision with a bad outcome is still a good decision. Judge yourself on adherence
  to written rules, not on whether the last trade won.
- Keep a decision journal: date, decision, reasoning, outcome, lesson. Over years, that
  journal — not any indicator — is what improves your returns.

## What this consultant will not do
- Predict prices. Nobody can; the spread of "expert" targets at any moment spans 5-10x.
- Recommend leverage, derivatives trading, or concentrated bets on low-cap tokens.
- Present a signal as advice. Signals here are **context with a transparent rationale**,
  never instructions.

*None of this is financial advice. It is a discipline framework. You are responsible for
every order you confirm.*
