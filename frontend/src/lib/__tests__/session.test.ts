import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { SAVE_REQUIRES_SIGN_IN, SIGN_IN_PROMPT, WATCHLISTS_SIGN_IN_PROMPT, myTradesView } from "@/lib/session";

const SRC = join(__dirname, "../..");
const read = (p: string) => readFileSync(join(SRC, p), "utf8");

describe("signed-out My Trades", () => {
  it("is the signed-out view whatever else is true: no rows, no counts, no controls", () => {
    expect(myTradesView(false, true, 0)).toBe("signed_out");
    expect(myTradesView(false, false, 7)).toBe("signed_out");
    expect(myTradesView(true, true, 0)).toBe("loading");
    expect(myTradesView(true, false, 0)).toBe("empty");
    expect(myTradesView(true, false, 3)).toBe("rows");
  });

  it("the notice renders its title, body and open path, and no control", () => {
    // vitest here has no JSX transform (tsconfig jsx: preserve), so the component is checked as source
    const src = read("components/SignedOutNotice.tsx");
    expect(src).toContain("{title}");
    expect(src).toContain("{body}");
    expect(src).toContain("openPath.href");
    expect(src).not.toMatch(/<button|onClick|Delete|Resolve/);
    expect(SIGN_IN_PROMPT.body).toContain("this browser is not signed in");
  });

  it("the page asks the browser before it asks the API, and returns the notice for signed_out", () => {
    const src = read("app/theses/page.tsx");
    const guard = src.indexOf("if (!isSignedIn())");
    const list = src.indexOf("api.theses.list()");
    expect(guard).toBeGreaterThan(0);
    expect(guard).toBeLessThan(list);
    expect(src).toMatch(/view === "signed_out"[\s\S]*<SignedOutNotice[\s\S]*SIGN_IN_PROMPT\.title/);
    expect(src).toContain("err.status === 401) setSignedIn(false)");
    // the rows branch, with its Delete and Resolve controls, is reached only through the view switch
    expect(src).toMatch(/view === "loading" \?[\s\S]*view === "empty" \?[\s\S]*<ThesisCard/);
  });
});

describe("signed-out Build a Trade", () => {
  it("can build and preview; saving is refused before the request with the reason", () => {
    const src = read("app/build/page.tsx");
    expect(src).toMatch(/async function handleSave\(\) \{[\s\S]{0,200}if \(!isSignedIn\(\)\) \{\s*setSaveError\(SAVE_REQUIRES_SIGN_IN\)/);
    expect(src).toMatch(/signedIn === false && \([\s\S]*\{SAVE_REQUIRES_SIGN_IN\}/);
    expect(src).toMatch(/signedIn !== false && \([\s\S]{0,300}onClick=\{handleSave\}/);
    // drafting stays open: the draft calls are not behind the sign-in guard
    expect(src.indexOf("api.theses.draft(")).toBeGreaterThan(0);
    expect(SAVE_REQUIRES_SIGN_IN).toContain("can be built and previewed but not saved");
  });
});

describe("signed-out Watchlists", () => {
  it("shows the notice instead of the failed-to-load box", () => {
    const src = read("app/watchlist/page.tsx");
    expect(src).toMatch(/if \(!isSignedIn\(\)\) \{\s*setWlStatus\("signed_out"\)/);
    expect(src).toMatch(/wlStatus === "signed_out" && \([\s\S]*WATCHLISTS_SIGN_IN_PROMPT\.title/);
    expect(src).toContain('err.status === 401 ? "signed_out" : "error"');
  });
});

describe("the notices claim only what the code does", () => {
  it("no notice promises a sign-in button or calls the ledger public", () => {
    for (const text of [SIGN_IN_PROMPT.body, WATCHLISTS_SIGN_IN_PROMPT.body, SAVE_REQUIRES_SIGN_IN]) {
      expect(text).not.toMatch(/sign in here|click|button|public ledger|Ivy's trades are public/i);
      expect(text).toContain("no public sign-in yet");
    }
  });
});

describe("a reviewer key in the same slot", () => {
  it("goes out in the same header, and the backend's 401 is what sends My Trades and Watchlists to the notice", () => {
    const api = read("lib/api.ts");
    expect(api).toContain('localStorage.getItem("admin_token")');
    expect(api).toContain('headers["X-Admin-Token"] = token');
    const session = read("lib/session.ts");
    expect(session).toContain('export const ADMIN_TOKEN_KEY = "admin_token"');
    expect(session).toContain("reviewer key");
    // My Trades and Watchlists: a stored key sends the request; the backend's 401 shows the notice
    expect(read("app/theses/page.tsx")).toContain("err.status === 401) setSignedIn(false)");
    expect(read("app/watchlist/page.tsx")).toContain('err.status === 401 ? "signed_out" : "error"');
    // Build a Trade: a refused save says why, with the same reason as a browser with no key
    expect(read("app/build/page.tsx")).toMatch(/err instanceof ApiError && err\.status === 401\) \{[\s\S]{0,200}setSignedIn\(false\);\s*setSaveError\(SAVE_REQUIRES_SIGN_IN\)/);
  });

  it("the Ivy pages take the ledger from the API and never from the browser's key", () => {
    for (const page of ["app/ivy/page.tsx", "app/ivy/desk/page.tsx", "app/ivy/trades/page.tsx"]) {
      const src = read(page);
      expect(src).not.toMatch(/isSignedIn|admin_token|ADMIN_TOKEN_KEY/);
    }
  });
});
