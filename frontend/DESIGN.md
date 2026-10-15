# Design rules

One design system on every page. `src/lib/__tests__/designRules.test.ts` enforces the rules marked (tested).

## Type scale

Four sizes, defined once as Tailwind tokens in `tailwind.config.ts`:

| Token | Size | Use |
|---|---|---|
| `text-display` | clamp(32px, 3.6vw, 52px), line height 1.1 | Page titles (every `h1`) and the home page's statements |
| `text-headline` | clamp(20px, 1.9vw, 24px), line height 1.25 | Section titles (every `h2` that is not a label) |
| `text-body` | 15px, line height 1.6 | Running text |
| `text-small` | 12px, line height 1.5 | Receipts, captions, footnotes |

Every `h1` uses `text-display` and every heading `h2` uses `text-headline` or `text-display` (tested). Labels stay in the one label
style: mono, 12px, uppercase, tracking .16em, muted.

## Dates

One format, from `src/lib/dates.ts` and nowhere else (tested):

- a date: **Oct 15, 2026**
- a time: **Oct 15, 2026, 4:00 PM ET** (always on the New York clock)

A chart axis alone may shorten its ticks (`axisDay` "Oct 15", `axisTime` "4:00 PM", a year tick "2026"). No page calls
`toLocaleDateString`, `toLocaleTimeString` or a dated `toLocaleString`, and no page prints a raw ISO date (tested).

## Color

- **Orange** is the brand: the wordmark, the home headline, Ivy's name on her Reads, Drafts and picks, the primary action button,
  the active navigation item, and at most the single most important number on a screen (Meet Ivy's hit rate). Nothing else is
  orange: no labels, pills, badges, link hovers or highlights.
- **Green and red** mean up and down, and nothing else: a price change, a profit or loss, a growth rate's sign. A beat is blue and a
  miss amber; a verified claim is plain, an unsupported one muted and a contradicted one amber; a highlight is plain and a risk amber.
- **Amber** is caution: a warning, a held figure, a contradiction.

## Underlines

An underline means "this opens an explanation": a term with a glossary entry or a figure with its receipt. It is one style, the
dotted `.explain-term` in `globals.css`. Links are never underlined; they read by color and their arrow. No `underline`,
`hover:underline` or `underline-offset` class appears in a page or component (tested).

## Home page

Every section after the opening sits in one column with one left edge (`HOME_COL`), and every one carries a label in the one label
style. The opening's heron is sized by the visible screen height on a phone (17svh, at most 150px), so the headline and both buttons
fit the first screen of an 844-point iPhone in Safari. The counters sit two by two on a phone.
