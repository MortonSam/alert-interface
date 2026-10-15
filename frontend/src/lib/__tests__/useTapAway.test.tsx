// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { useTapAway } from "@/lib/useTapAway";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let seen: false | undefined = undefined;
function Probe() {
  const { ref, tooltipActive } = useTapAway();
  seen = tooltipActive;
  return <div><div ref={ref} id="chart">chart</div><p id="outside">text</p></div>;
}

describe("chart tooltips close on a tap outside", () => {
  it("a press outside the chart hides the tooltip; a press inside hands it back to the chart", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => root.render(<Probe />));
    expect(seen).toBeUndefined();
    await act(async () => { document.getElementById("outside")!.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
    expect(seen).toBe(false);
    await act(async () => { document.getElementById("chart")!.dispatchEvent(new Event("touchstart", { bubbles: true })); });
    expect(seen).toBeUndefined();
    await act(async () => root.unmount());
  });
});
