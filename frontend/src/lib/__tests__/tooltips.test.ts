import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { PC_CALL_HEAVY, PC_PUT_HEAVY } from "@/lib/thresholds";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");
const BACKEND = join(SRC, "../../backend/app");

describe("tooltips describe what the code does (audit item 11)", () => {
  it("the put/call tooltip states the rule the label applies, from the mirrored constants", async () => {
    const { default: GLOSSARY } = await import("@/lib/glossary");
    const text = GLOSSARY["put/call ratio"];
    expect(text).toContain(`above ${PC_PUT_HEAVY} reads put-heavy`);
    expect(text).toContain(`below ${PC_CALL_HEAVY} reads call-heavy`);
    expect(text).not.toContain("1.0");
    const backend = readFileSync(join(BACKEND, "thresholds.py"), "utf8");
    expect(backend).toContain("if ratio > PC_PUT_HEAVY:");
    expect(backend).toContain("if ratio < PC_CALL_HEAVY:");
  });

  it("the peer average says the company is included, which is how the nightly computes it", async () => {
    const { default: GLOSSARY } = await import("@/lib/glossary");
    expect(GLOSSARY["peer average"]).toContain("this company included");
    expect(GLOSSARY["peer average"]).not.toContain("other stocks");
    expect(read("app/tickers/[symbol]/page.tsx")).toContain("names in the sector, this one included");
    const script = readFileSync(join(BACKEND, "scripts/compute_sector_peers.py"), "utf8");
    expect(script).toMatch(/peer_avgs = \[ticker_data\[s\]\["avg_abs_1d"\] for s in symbols/);   // every name in the sector, itself included
  });

  it("the index-removal tooltip says updates stop once the name is retired, which deactivate_tickers does", async () => {
    const { default: GLOSSARY } = await import("@/lib/glossary");
    expect(GLOSSARY["index-removal"]).toContain("updates stop");
    expect(GLOSSARY["index-removal"]).toContain("refreshes on the same schedule as every other");
    expect(GLOSSARY["index-removal"]).not.toContain("continues to update normally");
    expect(readFileSync(join(BACKEND, "scripts/deactivate_tickers.py"), "utf8")).toContain("is_active");
    expect(readFileSync(join(BACKEND, "scripts/audit_sp500.py"), "utf8")).toContain("index_member");
  });

  it("the Outcome tooltip describes the badge and the surprise beside it, and no arrow", () => {
    const page = read("app/tickers/[symbol]/page.tsx");
    const m = page.match(/title="(Beat, Miss or Meet[^"]*)"/);
    expect(m).not.toBeNull();
    expect(m![1]).toContain("the surprise printed beside it");
    expect(m![1]).toContain("1d, 3d and 5d columns");
    expect(m![1]).not.toMatch(/arrow/);
    expect(page).toContain("<OutcomeBadge outcome={r.outcome} reason={r.outcome_reason} />");
    expect(page).toContain("fmtEpsSurprise(r)");
  });
});

describe("Discover names what it is (audit item 12)", () => {
  it("the suggestion section is not called Ivy's picks and its numbering never skips", () => {
    const page = read("app/discover/page.tsx");
    expect(page).not.toMatch(/Ivy&apos;s Picks|From Ivy|Stocks Ivy thinks/);
    expect(page).toContain('label="Suggestion score"');
    expect(page).toContain("Not Ivy&apos;s rule; her picks are on the ledger.");
    expect(page).not.toMatch(/index="0\d"/);
    expect(page.match(/index=\{nextIndex\(\)\}/g)?.length).toBe(5);
    expect(page).toContain('const nextIndex = () => String(++sectionN).padStart(2, "0");');
  });
});
