"""Los 5 playbooks del consultor (capa 7). Cada prompt devuelve un plan de trabajo en
texto que el cliente LLM ejecuta con las tools del server; el PRIMER paso siempre es
leer los resources que gobiernan la interpretación (los clientes no los leen solos)."""
from __future__ import annotations

_GROUNDING = (
    "GROUNDING (do this first): read `kb://discipline` and `kb://research/no-edge`. "
    "Every conclusion you produce must be consistent with them: no price predictions, "
    "no timing calls, signals are context not advice, and this is not financial advice.\n"
)


def portfolio_review(risk_profile: str = "conservative") -> str:
    """Methodical portfolio review: balances, market context, derivatives, news, verdict."""
    return (
        _GROUNDING
        + f"You are reviewing a crypto portfolio for a {risk_profile} investor. Steps:\n"
        "1. `binance_get_balance` — the actual holdings (never assume).\n"
        "2. `binance_get_price` / `binance_get_ticker_24h` for each held asset → value "
        "each position and the total. Compute concentration (% per asset).\n"
        "3. `binance_analyze_portfolio` — pass the user's cost basis if they provide it "
        "(ask once; do not insist) plus their tax_rate/cashout_spread for NET break-even.\n"
        "4. `binance_get_market_structure` — Fear & Greed, BTC dominance, market cap "
        "trend. Interpret with `kb://frameworks/cycle-analysis`.\n"
        "5. `binance_get_derivatives` for BTCUSDT (and the largest altcoin held) — is "
        "leverage crowded? (see `kb://glossary`: funding, OI).\n"
        "6. `binance_get_news(limit=15)` — apply `kb://frameworks/news-analysis`: did "
        "anything change flows, rules, or structure?\n"
        "7. Verdict, structured as: state of the portfolio (facts) → what changed since "
        "the last review → risks by size (concentration first) → what the DISCIPLINE "
        "says to do (usually: nothing; say so plainly when true) → what would change "
        "the assessment (falsifiable). Flag any position >70% (concentration) and any "
        "altcoin lacking a value-capture thesis (`kb://frameworks/token-value`).\n"
        "Never recommend leverage, never predict prices, close with the disclaimer."
    )


def asset_thesis(symbol: str) -> str:
    """Build an honest investment thesis for one asset using the value-capture framework."""
    return (
        _GROUNDING
        + f"Build an investment thesis for {symbol}. Steps:\n"
        "1. Read `kb://frameworks/token-value` — the five questions govern everything.\n"
        f"2. `binance_get_ticker_24h`/`binance_get_klines` for {symbol} (price context, "
        "NOT the thesis).\n"
        f"3. `binance_get_news(asset=...)` for the base asset + `binance_get_sentiment` "
        "— classify each item with `kb://frameworks/news-analysis` (primary vs "
        "derivative; flows/rules/structure).\n"
        f"4. `binance_get_derivatives` for {symbol} if it has a liquid perp — "
        "positioning check.\n"
        "5. Answer the five value-capture questions explicitly. Mark every claim as "
        "VERIFIED (with source) or UNVERIFIED. The unverifiable claims usually decide.\n"
        "6. Output the verdict template from the framework: bull case (verified), bear "
        "case (verified), the open question the price depends on, and the anchoring "
        "check ('would I buy it today at this price?'). If the asset is not BTC, state "
        "what it must offer over BTC to justify its extra risk.\n"
        "No price targets. Close with the disclaimer."
    )


def market_briefing() -> str:
    """Daily/weekly market briefing: what to read and what actually changed."""
    return (
        _GROUNDING
        + "Produce a market briefing without hype. Steps:\n"
        "1. Read `kb://sources` — weight every input by its annotated bias.\n"
        "2. `binance_get_market_structure` — F&G (and its direction), dominance, mcap.\n"
        "3. `binance_get_derivatives` BTCUSDT — funding/OI: crowded or washed out?\n"
        "4. `binance_get_news(limit=20)` — bucket into flows / rules / structure / "
        "narrative-only (per `kb://frameworks/news-analysis`). Note anything within "
        "±48h of a `kb://macro-calendar` date.\n"
        "5. Brief: 'What actually changed: [...]. What is loud but changes nothing: "
        "[...]. What to watch next: [...] (with dates).' If nothing structural "
        "happened, the correct briefing SAYS nothing happened.\n"
        "ETF flows: no free API — if flows matter today, cite news coverage or point "
        "the user to Farside in a browser (per `kb://sources`)."
    )


def risk_check(portfolio_description: str = "") -> str:
    """Stress-test the current portfolio: concentration, volatility, drawdown rehearsal."""
    extra = f" Context from the user: {portfolio_description}." if portfolio_description else ""
    return (
        _GROUNDING
        + "Run a risk check on the actual portfolio." + extra + " Steps:\n"
        "1. `binance_get_balance` + prices → position sizes and concentration.\n"
        "2. `binance_assess_risk` — realized vol, max historical drawdown, correlation "
        "to BTC per held asset.\n"
        "3. Rehearse the drawdown (discipline rule 2): show the portfolio value if BTC "
        "falls 30% / 50% / 75% with each asset moving by its historical beta. State the "
        "numbers plainly — the point is to feel them BEFORE the market does it.\n"
        "4. Leverage state around the portfolio: `binance_get_derivatives` — external "
        "fragility that could amplify moves.\n"
        "5. Output: concentration risks ranked, the 'can the user hold through -75%?' "
        "question answered honestly, and any position whose loss would be unacceptable "
        "→ the discipline answer is SIZE, never timing. No predictions, disclaimer."
    )


def dca_plan(monthly_amount: str, quote_asset: str = "USDT") -> str:
    """Design a disciplined, unconditional DCA plan with cold-blooded exit rules."""
    return (
        _GROUNDING
        + f"Design a DCA plan for {monthly_amount} {quote_asset} per month. Steps:\n"
        "1. Read `kb://discipline` rules 1, 2, 4 and 5 — they ARE the plan's skeleton.\n"
        "2. Allocation: default to the highest-quality asset (BTC) unless the user "
        "holds a verified thesis for something else (`kb://frameworks/token-value`). "
        "High-beta assets only as a minor, capped share.\n"
        "3. Mechanics: fixed day of month, unconditional (no dip-waiting — that is "
        "timing, see `kb://research/no-edge`), spot only, never leverage.\n"
        "4. Write the COLD-BLOOD rules with the user: the drawdown they pre-accept "
        "without selling; harvest levels (fixed % at fixed prices, written now); the "
        "falsifiable thesis-broken condition; and the NET break-even math "
        "(`binance_analyze_portfolio` with their tax_rate/spread).\n"
        "5. Ground the plan in history: run `binance_backtest_dca` for the chosen "
        "asset/amount over 2-3 different windows — show the user the max drawdown they "
        "are signing up for and the honest lump-sum comparison.\n"
        "6. Cadence: a short monthly review (this server's `portfolio_review` prompt); "
        "explicitly forbid daily balance-watching in drawdowns.\n"
        "Deliver the plan as written rules the user can paste somewhere permanent. "
        "Not financial advice; the user owns every decision."
    )
