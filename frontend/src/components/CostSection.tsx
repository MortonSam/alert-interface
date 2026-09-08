"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

function fmt(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

export function CostSection() {
  const ref = useRef<HTMLElement>(null);
  const numRef = useRef<HTMLSpanElement>(null);
  const subFrom = useRef<HTMLSpanElement>(null);
  const subTo = useRef<HTMLSpanElement>(null);
  const marker = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        // Hide "ALERT INTERFACE" sublabel initially
        gsap.set(subTo.current, { opacity: 0 });

        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: ref.current,
            pin: true,
            scrub: true,
            start: "top top",
            end: "+=150%", // ~1.5 viewport heights
          },
        });

        // Countdown $30,000 → $0
        tl.to(
          { val: 30000 },
          {
            val: 0,
            duration: 1,
            ease: "none",
            onUpdate() {
              if (numRef.current) {
                numRef.current.textContent = fmt(
                  (this as unknown as { targets(): { val: number }[] }).targets()[0].val,
                );
              }
            },
          },
          0,
        );

        // Crossfade sublabels
        tl.to(subFrom.current, { opacity: 0, duration: 0.3 }, 0.35);
        tl.to(subTo.current, { opacity: 1, duration: 0.3 }, 0.5);

        // Slide the scale marker from top to bottom
        tl.fromTo(
          marker.current,
          { top: "0%" },
          { top: "100%", duration: 1, ease: "none" },
          0,
        );
      });

      // Reduced motion: show static end state
      mm.add("(prefers-reduced-motion: reduce)", () => {
        if (numRef.current) numRef.current.textContent = "$0";
        gsap.set(subFrom.current, { opacity: 0 });
        gsap.set(subTo.current, { opacity: 1 });
        if (marker.current) marker.current.style.top = "100%";
      });
    },
    { scope: ref },
  );

  return (
    <section
      ref={ref}
      className="h-[100dvh] flex items-center justify-center px-8 relative"
    >
      <div className="text-center">
        <p className="font-mono text-xs uppercase tracking-[.16em] text-primary mb-6">
          The cost
        </p>
        <span
          ref={numRef}
          className="stat-number font-display font-bold text-foreground block"
        >
          $30,000
        </span>
        <div className="relative mt-3 h-6">
          <span
            ref={subFrom}
            className="absolute inset-x-0 font-mono text-xs uppercase tracking-[.16em] text-muted-foreground"
          >
            Per year
          </span>
          <span
            ref={subTo}
            className="absolute inset-x-0 font-mono text-xs uppercase tracking-[.16em] text-primary"
          >
            Alert Interface
          </span>
        </div>
      </div>

      {/* Vertical scale — right edge */}
      <div className="absolute right-8 top-1/2 -translate-y-1/2 h-[40vh] hidden md:flex flex-col items-end">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-2">
          Traditional research
        </span>
        <div className="relative flex-1 w-px bg-border">
          <div
            ref={marker}
            className="absolute left-1/2 -translate-x-1/2 w-2 h-2 rounded-full bg-primary"
            style={{ top: "0%" }}
          />
        </div>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60 mt-2">
          Alert Interface
        </span>
      </div>
    </section>
  );
}
