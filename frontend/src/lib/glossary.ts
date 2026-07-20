/**
 * Plain-English glossary for options & earnings terms.
 * Each definition ≤ 20 words, written for someone who has never traded options.
 */

const GLOSSARY: Record<string, string> = {
  straddle:
    "Buying both a call and put at the same strike. The total cost reflects the market's expected move.",
  "atm strike":
    "The strike price closest to where the stock trades right now.",
  "implied move":
    "How much the options market expects the stock to move, in either direction, by expiration.",
  "implied range":
    "The price band the market expects the stock to stay within by expiration.",
  "realized volatility":
    "How much the stock has actually moved recently, measured from daily price changes over a set window.",
  "rv rank":
    "Where today's realized volatility falls within its own range over the past year (0 = lowest, 100 = highest).",
  percentile:
    "The percentage of past trading days where realized volatility was lower than today's level.",
  iv:
    "Implied volatility — the market's forecast of future stock movement, priced into options. Higher IV means pricier options.",
  "iv/rv spread":
    "The gap between implied volatility and realized volatility. Positive means options are priced above recent actual movement.",
  "put/call ratio":
    "Total put volume divided by call volume. Above 1.0 means more bearish bets; below 1.0 means more bullish bets.",
  breakeven:
    "The stock price where an option trade starts to profit, accounting for the premium paid.",
  beat:
    "The company reported earnings per share above analyst estimates.",
  miss:
    "The company reported earnings per share below analyst estimates.",
  expiration:
    "The date an options contract expires. After this date the contract is worthless if not exercised.",
  premium:
    "The price paid to buy an option. This is the most you can lose as a buyer.",
  "ex-dividend":
    "The date a stock begins trading without its upcoming dividend. Buy before this date to receive the payout.",
  "stock-split":
    "A corporate action that divides existing shares into multiple new shares, lowering the per-share price proportionally while keeping total market value unchanged.",
  "index-removal":
    "This stock was removed from the S&P 500 index. It remains tradable and data continues to update normally.",
  "analyst-action":
    "A Wall Street analyst changed their rating, price target, or coverage status on this stock.",
};

export default GLOSSARY;
