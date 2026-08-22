# Macro calendar — the dates that move crypto

Static, versioned resource. **Last verified: 2026-08-22.** Sources: federalreserve.gov
(FOMC schedule, published a year ahead), bls.gov (CPI release schedule). If today is past
the horizon below, ask the user to allow a web check or consult the primary sources.

## Why these dates matter
Crypto trades as a liquidity-sensitive risk asset. The two recurring events that reprice
liquidity expectations are the **FOMC decision** (rates) and the **CPI print** (inflation
→ rate expectations). Around them: elevated volatility in BOTH directions, crowded
leverage gets flushed (check `binance_get_derivatives` before and after).

## FOMC meetings (decision days, federalreserve.gov)
- 2026: Sep 15-16 · Oct 27-28 · Dec 8-9
- 2027: schedule published by the Fed each June for the following year — verify at
  federalreserve.gov/monetarypolicy/fomccalendars.htm
- Jackson Hole Economic Symposium: late August each year (2026: Aug 27-29).

## US CPI releases (8:30 ET, bls.gov)
Monthly, typically the second week. Verify the exact dates at
bls.gov/schedule/news_release/cpi.htm before citing a specific day.

## Crypto-native structural dates
- **Bitcoin halving #5: estimated April 2028** (block 1,050,000). Block-height based —
  the date drifts with hashrate; recompute from current height (`binance_get_market_structure`
  exposes network data) at ~144 blocks/day.
- Historical pattern context: `kb://frameworks/cycle-analysis`.

## How to use this calendar
1. Before interpreting any sharp move, check whether it sits within ±48h of one of these
   dates — if yes, the move is probably macro, not crypto-specific news.
2. Never advise position changes *because* an event is coming (that is timing). The
   calendar exists to *interpret* volatility, not to trade it.
