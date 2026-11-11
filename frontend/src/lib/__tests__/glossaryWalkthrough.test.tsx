// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const LEDGER = "The ledger's figures do not include it.";
const SITE = "The site's hypothetical results do not include it.";

/** A fresh copy of the tip and its flag (the browser's answer is kept per page load), with /ivy-page answering `status`. */
async function mount(status: number) {
  vi.resetModules();
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => { calls.push(String(url)); return { ok: status === 200, status, json: async () => ({ minutes: 3 }) }; });
  const { default: ExplainTip } = await import("@/components/ticker/ExplainTip");
  const { default: WalkthroughText } = await import("@/components/WalkthroughText");
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const tip = (term: string) => <ExplainTip term={term}>{term}</ExplainTip>;
  const hover = async (): Promise<string | null> => {
    const button = host.querySelector("[role=button]");
    if (!button) return null;
    await act(async () => { button.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    const text = document.querySelector("[role=dialog]")?.textContent ?? null;
    await act(async () => { button.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    return text;
  };
  return { calls, root, host, tip, hover, WalkthroughText };
}

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("a glossary tip follows the walkthrough flag (Sam, 2026-11-11)", () => {
  it("by the server's reading where a page hands one down, without asking again", async () => {
    for (const [on, want] of [[false, LEDGER], [true, SITE]] as const) {
      const m = await mount(on ? 404 : 200);                      // the browser would say the opposite: it is never asked
      await act(async () => m.root.render(<m.WalkthroughText on={on}>{m.tip("slippage")}</m.WalkthroughText>));
      expect(await m.hover()).toContain(want);
      expect(m.calls).toEqual([]);
      await act(async () => m.root.unmount());
    }
  });
  it("by the browser's own reading elsewhere, asked once per page load and only for a term that differs", async () => {
    const on = await mount(200);
    await act(async () => on.root.render(<>{on.tip("slippage")}{on.tip("momentum")}{on.tip("receipt")}{on.tip("implied range")}</>));
    expect(on.calls).toEqual(["/api/v1/ivy-page"]);
    expect([...on.host.querySelectorAll("[role=button]")].map((b) => b.textContent)).toEqual(["slippage", "momentum", "implied range"]);   // "receipt" is retired
    expect(await on.hover()).toContain(SITE);
    await act(async () => on.root.unmount());

    const off = await mount(404);
    await act(async () => off.root.render(<>{off.tip("slippage")}{off.tip("receipt")}</>));
    expect(off.calls).toEqual(["/api/v1/ivy-page"]);
    expect(off.host.querySelectorAll("[role=button]").length).toBe(2);
    expect(await off.hover()).toContain(LEDGER);
    await act(async () => off.root.render(<>{off.tip("slippage")}{off.tip("receipt")}{off.tip("momentum")}</>));
    expect(off.calls.length).toBe(1);                              // a tip that mounts later does not ask again
    await act(async () => off.root.unmount());

    const same = await mount(200);
    await act(async () => same.root.render(same.tip("implied range")));
    expect(same.calls).toEqual([]);
    await act(async () => same.root.unmount());
  });
});
