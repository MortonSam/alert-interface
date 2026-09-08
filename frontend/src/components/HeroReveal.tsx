"use client";

import { useRef, type ReactNode } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";

export function HeroReveal({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const lines = ref.current!.querySelectorAll("[data-hero-line]");
        const fades = ref.current!.querySelectorAll("[data-hero-fade]");

        // Start hidden
        gsap.set([...lines, ...fades], { opacity: 0, y: 16 });

        const tl = gsap.timeline({ defaults: { ease: "power3.out" } });

        // Stagger the three headline lines
        tl.to(lines, {
          opacity: 1,
          y: 0,
          duration: 0.5,
          stagger: 0.15,
        });

        // Then the sub elements
        tl.to(
          fades,
          {
            opacity: 1,
            y: 0,
            duration: 0.6,
            stagger: 0.1,
          },
          "-=0.15",
        );
      });
    },
    { scope: ref },
  );

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
