// Renders the main pages in Chrome, Safari's engine (WebKit) and Firefox at 390 and 1440 wide, and fails on any section whose text is
// invisible or empty (Sam, 2026-10-29: the home page showed empty sections in Safari). A section is checked twice: as the first paint
// leaves it, before any scrolling (content must never wait for an animation), and after scrolling through the page.
//   node scripts/visible-sections-check.mjs [base] [engines]     (default http://localhost:3000, "chromium,webkit,firefox")
// playwright is resolved from PLAYWRIGHT_DIR when set (it is not a dependency of the site).
import { createRequire } from "node:module";

const base = (process.argv[2] || "http://localhost:3000").replace(/\/$/, "");
const engines = (process.argv[3] || "chromium,webkit,firefox").split(",");
const req = createRequire(process.env.PLAYWRIGHT_DIR ? `${process.env.PLAYWRIGHT_DIR}/` : import.meta.url);
const pw = req("playwright");
const ROUTES = ["/", "/tickers/NVDA", "/discover", "/build", "/ivy"];
const WIDTHS = [390, 1440];
const MIN_SHOWN = 0.15;          // an element's effective opacity (its own times every ancestor's) below this is invisible

// in the page: every section taller than 40px whose text is empty, or whose text-bearing elements are mostly invisible
function invisibleSections(minShown) {
  const eff = (el) => {
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.visibility === "hidden" || cs.display === "none") return 0;
      o *= parseFloat(cs.opacity);
    }
    const c = getComputedStyle(el).color.match(/rgba?\(([^)]+)\)/);
    const alpha = c && c[1].split(",").length === 4 ? parseFloat(c[1].split(",")[3]) : 1;
    return o * alpha;
  };
  const out = [];
  for (const s of document.querySelectorAll("main section")) {
    const r = s.getBoundingClientRect();
    if (r.height <= 40 || getComputedStyle(s).display === "none") continue;
    const text = (s.innerText || "").trim();
    let shown = 0, total = 0;
    for (const el of s.querySelectorAll("h1,h2,h3,h4,p,li,a,button,td,dd,dt")) {
      if (!(el.innerText || "").trim()) continue;
      total += 1;
      if (eff(el) >= minShown) shown += 1;
    }
    if (!text || eff(s) < minShown || (total && shown / total < 0.5)) {
      out.push(`${s.id ? "#" + s.id : (s.querySelector("h1,h2,h3")?.innerText || text).slice(0, 50) || "(empty)"}: ${shown} of ${total} text elements shown`);
    }
  }
  return out;
}

let failed = 0, checked = 0;
for (const name of engines) {
  const browser = await pw[name].launch(process.env.CI && name === "chromium" ? { args: ["--no-sandbox"] } : {});
  for (const path of ROUTES) for (const w of WIDTHS) {
    const phone = w === 390;
    const ctx = await browser.newContext({ viewport: { width: w, height: phone ? 844 : 900 }, ...(phone && name !== "firefox" ? { isMobile: true, hasTouch: true } : {}) });
    const page = await ctx.newPage();
    const tag = `${name} ${w} ${path}`;
    checked += 1;
    try {
      await page.goto(base + path, { waitUntil: "load", timeout: 60000 });
      await page.waitForTimeout(4000);                              // past the home page's MOTION_DONE_MS: nothing may still be hidden
      const first = await page.evaluate(invisibleSections, MIN_SHOWN);
      for (let i = 0; i < 25; i++) { await page.evaluate(() => window.scrollBy(0, 800)); await page.waitForTimeout(100); }
      await page.waitForTimeout(1500);
      const after = await page.evaluate(invisibleSections, MIN_SHOWN);
      const bad = [...new Set([...first.map((x) => `before scrolling, ${x}`), ...after.map((x) => `after scrolling, ${x}`)])];
      if (bad.length) { failed += 1; console.log(`FAIL ${tag}`); bad.slice(0, 8).forEach((x) => console.log(`  ${x}`)); }
      else console.log(`ok   ${tag}`);
    } catch (e) { failed += 1; console.log(`FAIL ${tag}: ${String(e).slice(0, 160)}`); }
    await ctx.close();
  }
  await browser.close();
}
console.log(`${checked} page view(s) in ${engines.join(", ")}, ${failed} failing`);
process.exit(failed ? 1 : 0);
