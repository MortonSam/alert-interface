# Build a Trade: new wording for Sam's approval (2026-11-02)

**Part B is held until you approve it** (branch `build-teach`, not pushed). **Part A shipped today** with fixes 1 and 2 (2a0e304, live); it's listed so you can see every new line in one place. Every line of the teaching panel lives in one file, `frontend/src/lib/tradeTeachingCopy.ts`, so a change to the wording is a change to that file alone. Every figure is worked out in code from the trade's own legs, with no model call (`frontend/src/lib/tradeTeaching.ts`).

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

## B. Held: the "What this trade does" panel and Go deeper

**Where:** above the cost cards, on every draft.

**Build a Trade drafts four structures today:** a single call, a single put, a call spread and a put spread. The panel also covers put and call credit spreads, straddles, strangles, covered calls and protective puts, so it's ready if those are added. Examples 3 to 5 show it on structures Build a Trade does not draft yet.

**Terms:** each of these terms gets its plain tooltip at its first use in the panel only: strike price, expiration, net debit, net credit, breakeven, straddle. Implied volatility is explained wherever it appears, as now.

**New glossary entry:** **Net credit**: "The cash a trade brings in when it is opened: what the contracts sold fetch, minus what any contracts bought cost."

**Moved under a "Go deeper" fold:**
- the simulator's "Black-Scholes projection" label;
- its "Simulated at IV … held constant …" line;
- its footnote, now "Simulated values use Black-Scholes with IV held constant.";
- the cost area's "Net debit $3.60 · spread width $10" line.

**Still visible, outside the fold:** the SIMULATED pill and a new line, "Simulated, not a forecast."

**One overlap for you to decide:** the existing "plain English" reading above the fact grid (`buildPlainEnglish`) says some of the same things as this panel. I've left it unchanged. Say if it should go.

### 1. BNY $145/$155 call spread (Sam's screenshot case)

> This is a call spread. A call spread is buying one call and selling another with a higher strike price: the call sold lowers the cost and caps the gain.  
> You pay $360 at the start: a net debit of $3.60 a share, for 100 shares.  
> It gains if BNY ends above $148.60 at expiration on Nov 20, 2026.  
> The breakeven is $148.60: the $145 strike price plus the $3.60 a share paid.  
> The gain stops growing at $155: past it, the most the trade can make is $640.  
> The most it can lose is $360, the amount paid.  
> At expiration on Nov 20, 2026:  
> - Above $155: a $640 gain, wherever it ends in that range.  
> - Between $145 and $155: the result grows by $100 for every $1 the stock rises, from a $360 loss at $145 to a $640 gain at $155.  
> - Below $145: a $360 loss, wherever it ends in that range.  

### 2. A single call (NVDA $220, illustrative prices)

> This is a call. A call is the right to buy 100 shares at its strike price until expiration; it gains when the stock ends above the strike price by more than the call cost.  
> You pay $840 at the start: $8.40 a share, for 100 shares.  
> It gains if NVDA ends above $228.40 at expiration on Dec 18, 2026.  
> The breakeven is $228.40: the $220 strike price plus the $8.40 a share paid.  
> There is no cap on the gain: it keeps growing as the stock rises.  
> The most it can lose is $840, the amount paid.  
> At expiration on Dec 18, 2026:  
> - Above $220: the result grows by $100 for every $1 the stock rises past $220, from an $840 loss there.  
> - Below $220: an $840 loss, wherever it ends in that range.  

### 3. A put credit spread (KO $90/$85, illustrative)

> This is a put credit spread. A put credit spread is selling one put and buying another with a lower strike price: the cash comes in at the start, and the put bought caps the loss.  
> You receive $140 at the start: a net credit of $1.40 a share, for 100 shares.  
> It gains if KO ends above $88.60 at expiration on Dec 18, 2026.  
> The breakeven is $88.60: the $90 strike price minus the $1.40 a share received.  
> The gain stops growing at $90: past it, the most the trade can make is $140.  
> The most it can lose is $360, if it ends at or below $85.  
> At expiration on Dec 18, 2026:  
> - Above $90: a $140 gain, wherever it ends in that range.  
> - Between $85 and $90: the result grows by $100 for every $1 the stock rises, from a $360 loss at $85 to a $140 gain at $90.  
> - Below $85: a $360 loss, wherever it ends in that range.  

### 4. A straddle (TSLA $450, illustrative)

> This is a straddle. A straddle is buying a call and a put with the same strike price and expiration: it gains when the stock moves far enough either way to cover both.  
> You pay $4,250 at the start: a net debit of $42.50 a share, for 100 shares.  
> It gains if TSLA ends below $407.50 or above $492.50 at expiration on Nov 20, 2026: a big enough move either way.  
> There are two breakevens, $407.50 and $492.50: the result at expiration is zero at each.  
> There is no cap on the gain as the stock rises; as it falls, the gain grows up to $40,750 if it reached $0.  
> The most it can lose is $4,250, the amount paid.  
> At expiration on Nov 20, 2026:  
> - Above $450: the result grows by $100 for every $1 the stock rises past $450, from a $4,250 loss there.  
> - Below $450: the result drops by $100 for every $1 the stock rises, from a $40,750 gain at $0 to a $4,250 loss at $450.  

### 5. A covered call (AAPL shares at $270 with the $285 call, illustrative)

> This is a covered call. A covered call is owning 100 shares and selling a call on them: the call brings in cash now, and any rise above its strike price goes to the call's owner instead.  
> You receive $310 at the start: a net credit of $3.10 a share, for 100 shares.  
> It assumes 100 shares held at $270.  
> It gains if AAPL ends above $266.90 at expiration on Dec 18, 2026.  
> The breakeven is $266.90: the $270 share price minus the $3.10 a share received.  
> The gain stops growing at $285: past it, the most the trade can make is $1,810.  
> The most it can lose is $26,690, if it ends at $0.  
> At expiration on Dec 18, 2026:  
> - Above $285: a $1,810 gain, wherever it ends in that range.  
> - Below $285: the result grows by $100 for every $1 the stock rises, from a $26,690 loss at $0 to a $1,810 gain at $285.  

### The structure sentences not shown above

- **A put:** "A put is the right to sell 100 shares at its strike price until expiration; it gains when the stock ends below the strike price by more than the put cost."
- **A put spread:** "A put spread is buying one put and selling another with a lower strike price: the put sold lowers the cost and caps the gain."
- **A call credit spread:** "A call credit spread is selling one call and buying another with a higher strike price: the cash comes in at the start, and the call bought caps the loss."
- **A strangle:** "A strangle is buying a call with a higher strike price and a put with a lower one: it costs less than a straddle and needs a bigger move either way."
- **A protective put:** "A protective put is owning 100 shares and buying a put on them: the put sets a floor under the shares until expiration, for what it costs."
- **Anything else:** "This is this combination. Its result at expiration is worked out below from each of its parts."

Screenshots of the five panels are in the report.
