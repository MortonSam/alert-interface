/**
 * Plain-English glossary for options & earnings terms.
 * Written for someone who has never traded options.
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
    "Implied volatility: the market's forecast of future stock movement, priced into options. Higher IV means pricier options.",
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
  meet:
    "The company reported earnings per share roughly in line with analyst estimates. The stock may still move because a meet removes surprise in either direction but does not guarantee a flat reaction.",
  "1d move":
    "The stock's percentage change one trading day after the earnings report. For pre-market reports (BMO), this is measured from the prior close to the event-day close. For after-close reports (AMC), it is measured from the event-day close to the next close. The window always starts at the last close before the report and ends one trading day later.",
  "3d move":
    "The stock's percentage change three trading days after the earnings report, measured from the same baseline as the 1-day move. It shows whether the initial reaction held, reversed, or extended.",
  "5d move":
    "The stock's percentage change five trading days (one week) after the earnings report, measured from the same baseline as the 1-day move. It shows whether the initial reaction persisted over the full trading week.",
  "continuation rate":
    "How often the stock's day-5 move stayed in the same direction as the day-1 move. A high rate means initial reactions tend to stick; a low rate means reversals are common.",
  "magnitude trend":
    "Whether recent earnings moves have been getting bigger or smaller compared to earlier ones. Look for 'heating up' or 'cooling' to gauge if reactions are growing or fading.",
  "peer average":
    "The average one-day earnings move across other stocks in the same sector. Compare this company's typical move to the peer average to see if it reacts more or less than its sector.",
  "priced in":
    "When a stock drops after beating estimates, the market may have already expected the good news and bid the price up beforehand. A high priced-in rate means beats often do not lead to gains.",
  "median next-day move":
    "The middle value of all one-day stock price changes following the event type. The median is less affected by outliers than the average, giving a more typical picture.",
  "analyst grades":
    "Rating labels like Buy, Overweight, Hold, Underweight, or Sell that Wall Street analysts assign. Higher ratings suggest the analyst expects the stock to outperform; lower ones suggest underperformance.",
  "expected move":
    "The dollar or percentage move the options market implies between now and a specific expiration. It is derived from the at-the-money straddle price and reflects the market's best guess at total movement.",
  upgrade:
    "An analyst raised their rating on the stock, for example from Hold to Buy. Look at the median next-day move to see how the stock has historically reacted to upgrades.",
  downgrade:
    "An analyst lowered their rating on the stock, for example from Buy to Hold. Look at the median next-day move to see how the stock has historically reacted to downgrades.",
  rv:
    "Realized volatility measures how much the stock has actually moved recently, based on daily price changes. Higher RV means the stock has been swinging more than usual.",
  atm:
    "At the money - the strike price closest to where the stock trades right now. ATM options have the highest time value and are the most sensitive to price changes.",
};

export default GLOSSARY;
