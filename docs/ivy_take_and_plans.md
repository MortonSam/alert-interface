# Your take and plans (Block 4, design only)

Status: approved design, nothing built. **Waits on a legal review** before any of it is built or shown: it puts concrete plans with
dollar amounts in front of a visitor right after a walkthrough, which is closer to personalised advice than anything on the site
today. The walkthrough (Block 3) ends at its summary and Compare; these two screens would come after the summary.

## Where it sits

Walkthrough steps 1 to 7, then the summary, then (new) **Your take**, then (new) **Plans**. Both are optional: the summary keeps
its three moves (compare, ask Ivy, see the full page) and gains a fourth, "What's your take?".

## Screen 1, Your take

The question: "What's your take on {company}?" Four answers, one tap each:

1. **It keeps rising.**
2. **It has peaked.**
3. **I'd own it, but the report worries me.**
4. **Not sure yet.**

Under the answers, one line reminds the visitor of the walkthrough, built by rule from the stored walkthrough (never by the
model), for example: "You saw Micron keep 81¢ of each sales dollar, up from a loss of 9¢ three years earlier, and a report expected
around Dec 15." The line picks the summary lines of steps 3 and 6 when shown, else the first two shown steps.

"Not sure yet" adds the stock to the visitor's watchlist (the existing watchlist, signed-in visitors only; signed-out visitors get
the sign-in prompt the watchlist already uses) and ends the flow with the summary's closing line. The other three open Plans,
ordered for that take (below).

## Screen 2, Plans

Plans are priced on **$1,000**, simplest first. Each plan is one card with the same five rows.

| Plan | What it is |
|---|---|
| Shares now | Buy $1,000 of shares at the last stored close. |
| Half now, half after | $500 now, $500 after the next report (the date and its confirmation from step 6). |
| Wait | Buy nothing until after the report; shows what waiting has cost or saved after past reports. |
| A defined-risk options structure | The cheapest defined-risk structure Build a Trade's desk would draft for the take (a call spread for "keeps rising", a put spread for "has peaked", a spread that expires before the report for "the report worries me"). |

Rows on every card:

1. **Report-swing exposure**: how much of the $1,000 is exposed to the next report's move, using the stock's typical report move
   (step 6) and, when a fresh chain exists, the options-implied move. Example: "A typical report moves it ±6.8%, about $68 on $1,000."
2. **Worst case from its own history**: the largest drop over the plan's holding period in the stock's stored price history
   (shares) or after its stored reports (around the report), with the date it happened.
3. For the options plan only: **cost**, **maximum loss**, and **the options-implied chance of profit** at expiration (lognormal at
   the at-the-money implied volatility, the method and receipt Build a Trade v2 already shows: IV, days, price, options data date),
   with "An estimate from option prices, not a forecast."
4. The data dates for every figure, as in the walkthrough.
5. **Open in Build a Trade**, pre-filled with the stock, the structure, the strikes and the expiration (the options plan), or the
   stock and $1,000 (the others).

Order by take: "keeps rising" and "the report worries me" show the plans in the table's order; "has peaked" shows Wait first,
then the options plan (a put spread), then the share plans with a note that they bet the other way from the take.

## Rules carried over

- Every number is rule-built from stored, dated data; the model writes nothing on these screens.
- No recommendation: the screens never say which plan to pick, and the summary's closing line ("Ivy doesn't make buy or sell
  calls.") stays at the foot of both screens.
- No score, no streaks, nothing stored about the take except the watchlist add (browser memory is allowed for the take itself,
  as the walkthrough keeps concepts).
- Every visible string goes through the wording file and Sam's approval before it ships.
