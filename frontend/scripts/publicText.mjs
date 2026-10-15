// What a public page never shows an anonymous visitor: token counts, model names, costs and developer messages (2026-10-15).
// Read by the browser check (public-pages-check.mjs, every public route rendered as an anonymous visitor) and by the vitest guard
// (lib/__tests__/publicText.test.ts), so the two hold one list.
export const FORBIDDEN = [
  ["token count", /\b\d[\d,]*\s+tokens?\b/i],
  ["model name", /\b(?:claude|sonnet|opus|haiku|gpt-?\d|anthropic)\b/i],
  ["cost", /\b(?:cost_usd|estimated cost|api cost|spend(?:ing)? today|\$\d+(?:\.\d+)? (?:in )?(?:api|model) (?:cost|spend))\b/i],
  ["developer message", /\b(?:regenerat\w*|cache[ds]?\b|cache miss|admin token|traceback|typeerror|stack trace|undefined|NaN|\[object Object\]|servable|null in its fact block)\b/],
];

// Every public route, as an anonymous visitor reaches it: the sitemap's public pages and a set of ticker pages that cover each state
// (a REIT, a renamed ticker, a merged-away ticker, a pending deal, an ordinary large cap).
export const TICKERS = ["TSLA", "NVDA", "JPM", "O", "VMRK", "STZ", "AES", "EA", "AVB"];

export function violations(text) {
  const out = [];
  for (const [kind, re] of FORBIDDEN) {
    const g = new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
    for (const m of text.matchAll(g)) out.push(`${kind}: "${text.slice(Math.max(0, m.index - 40), m.index + m[0].length + 40).replace(/\s+/g, " ")}"`);
  }
  return out;
}
