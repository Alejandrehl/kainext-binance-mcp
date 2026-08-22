# Cycle analysis framework

Bitcoin has moved in roughly four-year cycles anchored to the halving (supply issuance
halves every 210,000 blocks). Whether that pattern persists is an **open debate** — treat
every cycle conclusion as probabilistic. `binance_analyze_cycle` computes the objective
inputs; this framework tells you how to read them.

## The objective inputs
1. **Distance to the next halving.** Historical pattern: cycle peaks arrived 12-18 months
   *after* a halving; deep bear bottoms roughly 12 months *before* it. This is a base
   rate from n≈4 samples — informative, far from a law.
2. **Drawdown from ATH.** Past bear markets bottomed at −77% to −84% from the peak
   (2011, 2014, 2018) and −50 to −60% in the amortized 2021-2022 and 2025-2026 cycles.
   Where the current drawdown sits inside that historical band says which regime you are in.
3. **Mayer Multiple** (price / 200-day moving average). Historically: < 0.8 marked deep
   value zones, > 2.4 marked euphoria. Between those, it says little. It is a *zone*
   indicator, never a timing tool.
4. **Leverage state** (`binance_get_derivatives`): sustained high positive funding with
   rising open interest marks crowded, fragile rallies; deeply negative funding marks
   capitulation. Cross-check any cycle read against it.

## The amortization debate (hold both hypotheses)
- **"The cycle is dampened"**: institutional flows (spot ETFs, corporate treasuries) buy
  drawdowns and sell strength, compressing amplitude — higher floors, lower blow-off tops.
  Proponents are mostly ETF managers (incentive alert).
- **"The cycle persists"**: the 2025 peak landed ~18 months post-halving, exactly on
  schedule; year-3 weakness is normal. Proponents (independent research desks) have the
  better track record but a smaller sample.
- Practical synthesis: expect the cycle's *shape* with reduced *amplitude*, and assign
  meaningful probability (~25-30%) to the pattern failing entirely in any given cycle.

## How to state a cycle conclusion (template)
"Inputs: drawdown X% from ATH, Mayer M, T months to the next halving, funding F.
These are most consistent with [accumulation / early expansion / euphoria / distribution /
capitulation], with the main alternative being [X]. Confidence: low/medium — n≈4 cycles.
What would change this read: [falsifiable condition]."

Never output a price target. Output a *phase*, its evidence, and its falsifier.
