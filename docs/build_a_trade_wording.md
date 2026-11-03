# Build a Trade: new wording for Sam's approval (2026-11-02)

**Part B: approved by Sam on Nov 2 with two changes**, both applied (it ships with this commit). **Part A shipped today** with fixes 1 and 2 (2a0e304, live); it's listed so you can see every new line in one place. Every line of the teaching panel lives in one file, `frontend/src/lib/tradeTeachingCopy.ts`, so a change to the wording is a change to that file alone. Every figure is worked out in code from the trade's own legs, with no model call (`frontend/src/lib/tradeTeaching.ts`).

## A. Shipped with fixes 1 and 2 (live)

| Where | Line |
|---|---|
| Simulator headline, slider before expiration | `BNY at $154.06 on Nov 10, 2026` |
| Simulator headline, slider at expiration | `BNY at $154.06 at expiration` (unchanged) |
| Price line, delayed quote | `priced at $145.20 from the Oct 30, 2026 options data; the stock is now $147.11 (Nov 2, 2026, 11:42 AM ET, delayed 15 min)`. The delay figure comes from the quote record. |
| Price line, a close | `... the stock is now $147.11 (Oct 30, 2026, 4:00 PM ET close)` |
| Option prices from an earlier session | `The option prices are from the Oct 30, 2026 session; the stock price is from Nov 2, 2026.` |
| Chart legend, the dashed vertical line | `The stock's latest price (its time is above the chart)` (was "Stock price when this was priced", which was wrong: the line marks the latest quote) |
| Ticker page options card, Ivy's trades, watchlist | A delayed quote is now dated "Nov 2, 2026, 11:42 AM ET, delayed 15 min", where it used to say "last trade". |

## A2. Pending approval, already live (research notes, ef0e25d, Nov 2): shipped before you approved them

These stay live until you decide. From now on no visitor-facing wording ships before you approve it.

| Where | Line | Source |
|---|---|---|
| Research note header, every note | `Written Oct 30, 2026` (replaced "Generated 3 days ago") | `frontend/src/lib/liveFigures.ts`, `writtenLabel` |
| Research note header, while a material 8-K is newer than the note | `Not yet in this note: the 8-K filed Nov 2, 2026`, linked to the filing | `frontend/src/lib/liveFigures.ts`, `pendingFilingLabel` |
| Tooltip on a live figure in a note's text (price, P/E, volatility and so on), once a note uses one | `last close, as of Oct 30, 2026`: the figure's name and its own date | `frontend/src/lib/liveFigures.ts`, `liveReceipt` |

## B. Approved Nov 2: the "What this trade does" panel and Go deeper

**Where:** above the cost cards, on every draft.

**Build a Trade drafts four structures today:** a single call, a single put, a call spread and a put spread. The panel also covers put and call credit spreads, straddles, strangles, covered calls and protective puts, so it's ready if those are added. Examples 3 to 5 show it on structures Build a Trade does not draft yet.

**Terms:** each of these terms gets its plain tooltip at its first use in the panel only: strike price, expiration, breakeven, straddle. Since the cost line was merged, the panel no longer says "net debit" or "net credit". Both stay under Go deeper and in the glossary. Implied volatility is explained wherever it appears, as now.

**New glossary entry:** **Net credit**: "The cash a trade brings in when it is opened, what the contracts sold fetch minus what any contracts bought cost."

**Approval changes (round 3, Nov 2):**
- The cost line and the 100-shares line are one line: "Option prices are quoted per share, and one contract covers 100 shares, so you pay $360 at the start ($3.60 a share)." It says "so you receive" for a credit trade. "For 100 shares" is gone, and a test fails if it comes back.
- A loss range with no floor above $0 reads "the loss grows by $100 for every $1 lower, up to $26,690 at $0." (the covered call below its breakeven). Bounded loss ranges keep "a loss that shrinks as the stock rises, largest at $145 ($360)".
- Approved as written: the covered call's "The most it can make is" line, and the punctuation-only changes to the net debit and breakeven tooltips, site-wide.

**Your review of Nov 2, applied (round 2):**
- Each stretch at expiration is told moving away from the breakeven, and every breakeven is one of the stretch boundaries. A gain "grows by $100 for every $1 higher (or lower)", ending "up to $640 at $155" when a strike stops it. A loss is "a loss that shrinks as the stock rises (or falls), largest at $145 ($360)". "Drops by ... for every $1 the stock rises" is gone, and a test fails if it comes back.
- After the cost line, once per panel, "Option prices are quoted per share, and one contract covers 100 shares."
- Covered call: the opening sentence says what you are doing, in the trade's own strike, and the most it can lose says the risk is in the shares and the call lowers it.
- Credit spreads: "You keep the full $140 if KO ends above $90." replaces "The gain stops growing at". For a call credit spread it reads "below" the lower strike. The covered call, also opened for a credit, gets "The most it can make is $1,810, if AAPL ends at or above $285." in that place (new line, for your approval).
- Every panel ends with "You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day."
- No colons. Colons became periods or commas, and "At expiration on Nov 20, 2026" is now a plain heading above the list. A test fails if any panel line has a colon. Semicolons are unchanged (the call and put sentences, and the straddle's no-cap line).
- **Two shared tooltips changed punctuation only**, because they open from the panel. These entries also show elsewhere on the site wherever the term appears.
  - **Net debit:** "What a two-part options trade costs to open, the price of the contract bought minus the price of the contract sold. It is also the most the trade can lose."
  - **Breakeven:** "The stock price at the contract's end date where the trade neither gains nor loses. It is the agreed price level plus (for a bet on a rise) or minus (for a fall) what the trade cost per share."

**Moved under a "Go deeper" fold:**
- the simulator's "Black-Scholes projection" label;
- its "Simulated at IV … held constant …" line;
- its footnote, now "Simulated values use Black-Scholes with IV held constant.";
- the cost area's "Net debit $3.60 · spread width $10" line.

**Still visible, outside the fold:** the SIMULATED pill and a new line, "Simulated, not a forecast."

**One overlap for you to decide:** the existing "plain English" reading above the fact grid (`buildPlainEnglish`) says some of the same things as this panel. I've left it unchanged. Say if it should go.

### 1. BNY $145/$155 call spread (Sam's screenshot case)

> This is a call spread. A call spread is buying one call and selling another with a higher strike price. The call sold lowers the cost and caps the gain.  
> Option prices are quoted per share, and one contract covers 100 shares, so you pay $360 at the start ($3.60 a share).  
> It gains if BNY ends above $148.60 at expiration on Nov 20, 2026.  
> The breakeven is $148.60, the $145 strike price plus the $3.60 a share paid.  
> The gain stops growing at $155. Past it, the most the trade can make is $640.  
> The most it can lose is $360, the amount paid.  
> At expiration on Nov 20, 2026  
> - Above $155, a $640 gain, wherever it ends in that range.  
> - Between $148.60 and $155, the gain grows by $100 for every $1 higher, up to $640 at $155.  
> - Between $145 and $148.60, a loss that shrinks as the stock rises, largest at $145 ($360).  
> - Below $145, a $360 loss, wherever it ends in that range.  
> You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day.  

### 2. A single call (NVDA $220, illustrative prices)

> This is a call. A call is the right to buy 100 shares at its strike price until expiration; it gains when the stock ends above the strike price by more than the call cost.  
> Option prices are quoted per share, and one contract covers 100 shares, so you pay $840 at the start ($8.40 a share).  
> It gains if NVDA ends above $228.40 at expiration on Dec 18, 2026.  
> The breakeven is $228.40, the $220 strike price plus the $8.40 a share paid.  
> There is no cap on the gain. It keeps growing as the stock rises.  
> The most it can lose is $840, the amount paid.  
> At expiration on Dec 18, 2026  
> - Above $228.40, the gain grows by $100 for every $1 higher.  
> - Between $220 and $228.40, a loss that shrinks as the stock rises, largest at $220 ($840).  
> - Below $220, an $840 loss, wherever it ends in that range.  
> You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day.  

### 3. A put credit spread (KO $90/$85, illustrative)

> This is a put credit spread. A put credit spread is selling one put and buying another with a lower strike price. The cash comes in at the start, and the put bought caps the loss.  
> Option prices are quoted per share, and one contract covers 100 shares, so you receive $140 at the start ($1.40 a share).  
> It gains if KO ends above $88.60 at expiration on Dec 18, 2026.  
> The breakeven is $88.60, the $90 strike price minus the $1.40 a share received.  
> You keep the full $140 if KO ends above $90.  
> The most it can lose is $360, if it ends at or below $85.  
> At expiration on Dec 18, 2026  
> - Above $90, a $140 gain, wherever it ends in that range.  
> - Between $88.60 and $90, the gain grows by $100 for every $1 higher, up to $140 at $90.  
> - Between $85 and $88.60, a loss that shrinks as the stock rises, largest at $85 ($360).  
> - Below $85, a $360 loss, wherever it ends in that range.  
> You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day.  

### 4. A straddle (TSLA $450, illustrative)

> This is a straddle. A straddle is buying a call and a put with the same strike price and expiration. It gains when the stock moves far enough either way to cover both.  
> Option prices are quoted per share, and one contract covers 100 shares, so you pay $4,250 at the start ($42.50 a share).  
> It gains if TSLA ends below $407.50 or above $492.50 at expiration on Nov 20, 2026, a big enough move either way.  
> There are two breakevens, $407.50 and $492.50, and the result at expiration is zero at each.  
> There is no cap on the gain as the stock rises; as it falls, the gain grows up to $40,750 if it reached $0.  
> The most it can lose is $4,250, the amount paid.  
> At expiration on Nov 20, 2026  
> - Above $492.50, the gain grows by $100 for every $1 higher.  
> - Between $450 and $492.50, a loss that shrinks as the stock rises, largest at $450 ($4,250).  
> - Between $407.50 and $450, a loss that shrinks as the stock falls, largest at $450 ($4,250).  
> - Below $407.50, the gain grows by $100 for every $1 lower.  
> You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day.  

### 5. A covered call (AAPL shares at $270 with the $285 call, illustrative)

> This is a covered call. You own 100 shares and sell someone the right to buy them from you at $285, which brings in cash now. If AAPL ends above $285, you sell at $285 and miss any rise past it.  
> Option prices are quoted per share, and one contract covers 100 shares, so you receive $310 at the start ($3.10 a share).  
> It assumes 100 shares held at $270.  
> It gains if AAPL ends above $266.90 at expiration on Dec 18, 2026.  
> The breakeven is $266.90, the $270 share price minus the $3.10 a share received.  
> The most it can make is $1,810, if AAPL ends at or above $285.  
> If AAPL fell to $0, you would lose $26,690, which is $310 less than owning the shares alone.  
> At expiration on Dec 18, 2026  
> - Above $285, a $1,810 gain, wherever it ends in that range.  
> - Between $266.90 and $285, the gain grows by $100 for every $1 higher, up to $1,810 at $285.  
> - Below $266.90, the loss grows by $100 for every $1 lower, up to $26,690 at $0.  
> You don't have to wait for expiration. You can close the trade earlier at whatever it's worth that day.  

### The structure sentences not shown above

- **A put:** "A put is the right to sell 100 shares at its strike price until expiration; it gains when the stock ends below the strike price by more than the put cost."
- **A put spread:** "A put spread is buying one put and selling another with a lower strike price. The put sold lowers the cost and caps the gain."
- **A call credit spread:** "A call credit spread is selling one call and buying another with a higher strike price. The cash comes in at the start, and the call bought caps the loss."
- **A strangle:** "A strangle is buying a call with a higher strike price and a put with a lower one. It costs less than a straddle and needs a bigger move either way."
- **A protective put:** "A protective put is owning 100 shares and buying a put on them. The put sets a floor under the shares until expiration, for what it costs."
- **Anything else:** "This is this combination. Its result at expiration is worked out below from each of its parts."

Screenshots of the five panels, and BNY's with the breakeven tooltip open, are in the report.

## C. Pending your approval: when Ivy can't write a new draft (not shipped)

**Why the line changes.** Today's line, "Drafting is busy today and paused until tomorrow. Browse the research notes meanwhile.", is not what happens. Drafting isn't busy. The day's AI budget has run out, and from this deploy, a draft already written today for the same stock, direction and risk level still opens. The line below says that and keeps the visitor on the page. The draft button stays, so a different choice that someone already drafted still opens.

**Where:** under the Generate button on Build a Trade, when the daily AI budget is reached. The per-visitor line ("You've used today's 5 free drafts…") is unchanged.

**Proposed (option 1, short):**
> Ivy can't write a new draft until midnight ET because today's drafting budget is used up. Drafts already written today still open, so another direction or risk level may work. Meanwhile, the {SYMBOL} page has Ivy's research note and what the options are pricing.

"the {SYMBOL} page" links to /tickers/{SYMBOL}.

**Proposed (option 2, shortest):**
> No new drafts until midnight ET, because today's drafting budget is used up. Drafts already written today still open. You can read Ivy's note on {SYMBOL} meanwhile.

**Facts each line rests on (for the claims rule):**
- "midnight ET": the cap resets at midnight New York time (`services/ai_spend.spend_day`).
- "Drafts already written today still open": `services/draft_cache` serves a draft written for the same stock, direction, risk level and options day, even with the cap reached. It's tested in `tests/test_ai_pools_and_draft_cache.py`. Strictly, it's the options day, not the calendar day. Until the next session's options data lands, yesterday's evening drafts still open.
- "Ivy's research note": shown only when {SYMBOL} has a served note. Otherwise the line names the options alone.
