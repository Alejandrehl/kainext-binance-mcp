# News analysis — separating signal from noise

A method, not a mood. Apply it to every batch from `binance_get_news`.

## 1. Classify before you react
For each item, ask in order:
1. **Primary or derivative?** A regulator's filing, a company's press release, an on-chain
   fact = primary. An article about someone's tweet about a rumor = derivative. Weight
   primary 10x.
2. **Does it change flows, rules, or structure?** The only three channels through which
   news moves prices durably: money flows (ETF creations, treasury buys), rules
   (legislation, SEC frameworks, tax), structure (halving, protocol upgrades, exchange
   failures). Anything else is narrative.
3. **Is it dated and falsifiable?** "Institution X bought Y on date Z" is checkable.
   "Institutions are accumulating" is not.

## 2. Score the source's incentive
See `kb://sources`. An ETF issuer predicting inflows, an exchange predicting volume, a
prediction site predicting anything — discount to near zero. A primary regulator document
or a dated flow table — full weight.

## 3. Sentiment is a thermometer, not a forecast
`binance_get_sentiment` is a deliberately crude lexicon count. Use it only to notice
*shifts* (a week of −0.3 turning +0.3 means the narrative flipped) — never levels, and
never as a trade trigger. Extreme readings coincide with extremes of positioning: greed
peaks near local tops, fear extremes near local bottoms, with wide error bars.

## 4. The weekly reading routine (15 minutes)
1. `binance_get_news(limit=20)` — headlines only; flag primaries.
2. `binance_get_market_structure` — F&G, dominance, mcap trend.
3. `binance_get_derivatives("BTCUSDT")` — funding/OI: is leverage crowded?
4. One question: **did anything change flows, rules, or structure this week?**
   If no: nothing happened, whatever the headlines say. If yes: read the primary source.

## 5. Traps
- **Recency amplification**: a 20% weekly move generates 10x the coverage of the quiet
  accumulation that preceded it. Coverage follows price; do not follow coverage.
- **Explanation theater**: every daily move gets a post-hoc narrative. Most daily moves
  are noise; an explanation does not make them signal.
- **Consensus at extremes**: when every source agrees, positioning is already crowded —
  the marginal buyer/seller is gone.
