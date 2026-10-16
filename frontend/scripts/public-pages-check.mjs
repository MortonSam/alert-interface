// Renders every public route in Chrome as an anonymous visitor (no admin token, no reviewer key, fresh profile) and fails on any
// token count, model name, cost or developer message in the page text, a tooltip's title included.
//   node scripts/public-pages-check.mjs [base]            (default http://localhost:3000)
// puppeteer-core is resolved from PUPPETEER_DIR when set (it is not a dependency of the site).
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { FORBIDDEN, TICKERS, violations } from "./publicText.mjs";

const base = (process.argv[2] || "http://localhost:3000").replace(/\/$/, "");
const req = createRequire(process.env.PUPPETEER_DIR ? `${process.env.PUPPETEER_DIR}/` : import.meta.url);
const puppeteer = req("puppeteer-core");
const sitemap = readFileSync(new URL("../src/app/sitemap.ts", import.meta.url), "utf8");
const PUBLIC_PATHS = JSON.parse(sitemap.match(/PUBLIC_PATHS = (\[[^\]]*\])/)[1]);
const routes = [...PUBLIC_PATHS, "/ivy/picks", "/theses", ...TICKERS.map((s) => `/tickers/${s}`)];

const browser = await puppeteer.launch({ executablePath: process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: "new",
  args: process.env.CI ? ["--no-sandbox"] : [] });   // a CI runner (GitHub Actions) has no usable Chrome sandbox
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
for (const path of routes) {
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  try {
    await page.goto(base + path, { waitUntil: "networkidle2", timeout: 60000 });
    await sleep(2000);
    for (let i = 0; i < 25; i++) { await page.evaluate(() => window.scrollBy(0, 800)); await sleep(80); }
    await sleep(1500);
    // the page's text, every title attribute, and every collapsed panel opened (a verification panel's claims, a "Why" disclosure)
    await page.evaluate(() => document.querySelectorAll("button[aria-expanded=false], details:not([open]) > summary").forEach((b) => { try { b.click(); } catch {} }));
    await sleep(800);
    // a news headline or its summary is a publisher's text, not ours: marked data-third-party and left out (TSLA's Dow Jones headline named Anthropic)
    await page.evaluate(() => document.querySelectorAll("[data-third-party]").forEach((e) => e.remove()));
    const text = await page.evaluate(() => document.body.innerText + "\n" + [...document.querySelectorAll("[title]")].map((e) => e.getAttribute("title")).join("\n"));
    const v = violations(text);
    if (v.length) { failed += 1; console.log(`FAIL ${path}`); v.slice(0, 10).forEach((x) => console.log(`  ${x}`)); }
    else console.log(`ok   ${path}`);
  } catch (e) { failed += 1; console.log(`FAIL ${path}: ${String(e).slice(0, 160)}`); }
  await page.close();
}
await browser.close();
console.log(`${routes.length} route(s), ${failed} failing; patterns: ${FORBIDDEN.map(([k]) => k).join(", ")}`);
process.exit(failed ? 1 : 0);
