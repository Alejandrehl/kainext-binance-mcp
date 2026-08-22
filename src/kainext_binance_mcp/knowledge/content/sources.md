# Source registry — what to read, and each source's bias

A consultant is only as good as its inputs. This is the curated list this server uses or
recommends, each with its bias annotated. **Rule zero: every source has an incentive;
read the incentive before the headline.**

## News (available via `binance_get_news`)
| Source | What it is good for | Bias / caveat |
|---|---|---|
| CoinDesk | Broadest institutional-grade coverage, policy, markets | Owned by a crypto group (Bullish); generally solid editorial wall |
| The Block | Data-driven reporting, funding/deals, infrastructure | Paywalled depth; headlines are reliable |
| Decrypt | Accessible coverage, ecosystem news | Lighter analysis; good breadth |
| crypto.news | High volume, fast | Quality varies widely; treat single-sourced claims as unverified |
| Federal Reserve press | Primary-source macro (FOMC statements, speeches) | No bias — it IS the source. Slow-moving but market-defining |

## Market data (available via tools)
| Data | Tool / source | Why it matters |
|---|---|---|
| Fear & Greed Index | `binance_get_market_structure` (alternative.me) | Sentiment thermometer. Extremes are informative; mid-range is noise |
| BTC dominance + total mcap | `binance_get_market_structure` (CoinGecko) | Rising dominance = risk-off within crypto; falling = alt speculation |
| Funding rates + open interest | `binance_get_derivatives` (Binance futures, public) | THE leverage thermometer: high positive funding + rising OI = crowded longs, squeeze fuel |
| On-chain fees + hashrate | `binance_get_market_structure` (mempool.space) | Network health and demand for blockspace |
| ATH + drawdown | `binance_analyze_cycle` (CoinGecko) | Where we are in the cycle, objectively |

## ETF flows — important, but no free API
Daily spot-ETF creations/redemptions are the cleanest read on institutional demand.
There is **no reliable free API**: Farside Investors (farside.co.uk) sits behind
Cloudflare, CoinGlass/SoSoValue require paid keys. What to do instead:
- Read Farside in a browser for the daily table (free, authoritative).
- Weekly flow totals are reliably covered by the news sources above — search recent
  items for "ETF" with `binance_get_news(asset="BTC")`.
- Treat any flow number quoted without a source as unverified.

## Sources to distrust by default
- **Price-prediction sites** ("$X by 2030"): content farms optimizing for search traffic.
- **ETF issuers' and exchanges' research** on crypto's future: they sell the asset class.
  Useful for data, never for conclusions.
- **Social media threads** without primary sources; engagement optimizes for extremes.
- **Anyone quoting "smart money" flows without a verifiable dataset.**

Reading method: `kb://frameworks/news-analysis`.
