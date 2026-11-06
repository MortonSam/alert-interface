# Walkthrough: a life-cycle step (design only, Sam's Nov 4 review)

Not built. This is the design for Sam to accept, change or drop before any code is written. Every figure it names already exists in stored, dated data; nothing new is fetched.

## What it teaches

Companies tend to move through stages: young and spending to grow, growing fast and profitably, mature and paying cash back to shareholders, or shrinking. Where a company sits explains much of what the other steps show: why its revenue grows fast or slowly, why its margins are thin or fat, why investors pay a lot or a little for each $1 of profit.

- **Question:** "Where is it in its life?"
- **Label:** "Life cycle"
- **Place:** after Margin (step 3), before Historical. It reads the two steps before it, and Valuation reads better after it. The walkthrough becomes eight steps, about 3½ minutes; `ENTRY_MIN_STEPS` stays 5.

## The rule (code, never the model)

From four stored figures, each with its date:

| Figure | Source on file | Use |
| --- | --- | --- |
| Revenue growth a year, over three fiscal years | `growth_figures` (the growth step's own quarters, summed by fiscal year) | how fast it is growing |
| Operating margin, last four quarters | `services/margins` (the margin step's own figure) | whether growing costs it money |
| Diluted share count, now against three years earlier | `eps_quarters.diluted_shares` | buying back shares, or issuing them |
| Dividends paid in the last year | stored ex-dividend dates and amounts (the dividend calendar) | paying cash back |

| Stage | When | Sentence (draft) |
| --- | --- | --- |
| Early | revenue growing 25% a year or more, and an operating loss | "{NAME} is spending to grow: revenue rose {x}% a year over three years, and it still loses money on its operations." |
| Fast growth | revenue growing 15% a year or more, and an operating profit | "{NAME} is growing fast and profitably: revenue rose {x}% a year over three years, and it keeps {m}¢ of operating profit on each $1." |
| Mature | revenue growing under 15% a year (but not shrinking), an operating profit, and a dividend or a share count down 3% or more | "{NAME} looks mature: revenue rose {x}% a year over three years, and it returns cash to shareholders ({a dividend of $d a share over the last year / its share count is down {s}% in three years})." |
| Shrinking | revenue down over three years | "{NAME}'s revenue fell {x}% a year over three years." |
| No stage | anything else (slow growth with no cash returned, a merger or spin-off inside the three years, fewer than twelve quarters on file) | the honest line, e.g. "Its revenue history spans a merger in {year}, so Ivy can't place it." |

The thresholds (25%, 15%, 3%, three years) are constants delivered by the API with the step, never retyped in copy, and a vitest mirrors them.

- **Banks, insurers and REITs:** no operating margin. Banks and insurers use revenue growth and cash returned only. REITs use FFO per share growth, and nearly all pay dividends by law, so the step says that.

## The quick check (draft)

- "{NAME} grew revenue {x}% a year and pays a dividend. What does that usually mean for how investors value it?"
- Options:
  1. "They pay less for each $1 of profit than for a fast grower" (right for Mature)
  2. "They pay more, because dividends are rare"
  3. "Dividends don't affect how a company is valued"
- The "why" is in dollars, like step 5's: "Investors pay more for each $1 of profit when they expect it to grow; a mature company's profit grows slowly, so each $1 usually costs less."

## The idea (draft)

- **Title:** "The life cycle"
- **Text:** "A young company spends to grow and often loses money. A fast grower is profitable and reinvests. A mature company grows slowly and pays cash back through dividends or buybacks. Knowing the stage tells you which numbers to watch."

## Example (illustrative only, not computed)

- **NVIDIA:** fast growth (revenue up well over 15% a year, high operating margin).
- **Coca-Cola:** mature (single-digit growth, dividend, share count roughly flat).

Both would be computed from stored figures before anything is shown.

## Open questions for Sam

1. Is "Life cycle" the right label?
2. Should it be its own step (eight steps), or a line inside Growth?
3. Should "Mature" require a dividend or buyback, or rest on growth alone?
4. Are 25%, 15% and 3% the right cut-offs? Once the rule is coded, a dry run over the 503 would show how many stocks land in each stage before anything is shown.
