/** A JSX attribute written as a quoted string ("...") is not a JS string: "±" in it reaches the page as six literal
 * characters. Every .tsx file is read and no quoted attribute value may carry a backslash escape; write the character itself,
 * or use an expression ({"±"}). */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "../..");

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "__tests__" || name === "node_modules" ? [] : tsxFiles(p);
    return p.endsWith(".tsx") ? [p] : [];
  });
}

// an attribute name, "=", then a double-quoted value holding a backslash escape (\uXXXX, \u{...}, \xXX, \n, \t)
const ATTR_ESCAPE = /\b[a-zA-Z][\w-]*="[^"{}]*\\(?:u[0-9a-fA-F]{4}|u\{|x[0-9a-fA-F]{2}|[nt])[^"]*"/g;

describe("no backslash escape in a quoted JSX attribute", () => {
  it("the pattern catches the case it is for and passes the expression form", () => {
    expect('<Explained text="Recent prints moving \\u00b1" />'.match(ATTR_ESCAPE)).not.toBeNull();
    expect('<Explained text={"Recent prints moving \\u00b1"} />'.match(ATTR_ESCAPE)).toBeNull();
    expect('<Explained text="Recent prints moving ±" />'.match(ATTR_ESCAPE)).toBeNull();
  });

  it("no .tsx file under src has one", () => {
    const hits = tsxFiles(SRC).flatMap(f => {
      const lines = readFileSync(f, "utf8").split("\n");
      return lines.flatMap((line, i) => (line.match(ATTR_ESCAPE) ?? []).map(m => `${f.slice(SRC.length + 1)}:${i + 1} ${m}`));
    });
    expect(hits).toEqual([]);
  });
});
