import { useEffect, useRef, useState } from "react";

/**
 * A chart tooltip closes on a tap (or click) outside its chart. Recharts keeps the last tooltip open on a touch screen until the
 * next touch lands on the chart; the chart's wrapper takes `ref`, and its <Tooltip> takes `active={tooltipActive}`: false after a
 * press outside, undefined (Recharts decides) after a press inside.
 */
export function useTapAway<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null);
  const [away, setAway] = useState(false);
  useEffect(() => {
    const onDown = (e: Event) => setAway(!(ref.current && e.target instanceof Node && ref.current.contains(e.target)));
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("touchstart", onDown, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("touchstart", onDown, true);
    };
  }, []);
  return { ref, tooltipActive: away ? (false as const) : undefined };
}
