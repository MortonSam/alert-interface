"use client";

import { useEffect, useRef, useState } from "react";

function easeOutQuart(t: number): number {
  return 1 - Math.pow(1 - t, 4);
}

export function CountUp({
  value,
  suffix = "",
  duration = 1000,
  className,
  title,
}: {
  value: number;
  suffix?: string;
  duration?: number;
  className?: string;
  title?: string;          // shown on hover: the date the number rests on
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [display, setDisplay] = useState(value.toLocaleString("en-US"));
  const triggered = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const prefersReduced =
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    // The real number is rendered from the first paint and stays unless the counter is seen: a headless or
    // non-scrolling render, a background tab or a throttled frame never shows 0. The count-up runs only
    // once the element is 30% visible, and then from 0 to the value.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !triggered.current) {
          triggered.current = true;
          observer.disconnect();
          setDisplay("0");
          const start = performance.now();
          function tick(now: number) {
            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            const current = Math.round(easeOutQuart(progress) * value);
            setDisplay(current.toLocaleString("en-US"));
            if (progress < 1) requestAnimationFrame(tick);
          }
          requestAnimationFrame(tick);
        }
      },
      { threshold: 0.3 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [value, duration]);

  return (
    <span ref={ref} className={className} title={title}>
      {display}
      {suffix}
    </span>
  );
}
