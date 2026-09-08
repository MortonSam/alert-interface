"use client";

import { useRef, type ReactNode } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

export function StoryFlow({
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
        const sections = gsap.utils.toArray<HTMLElement>(
          ref.current!.querySelectorAll(":scope > section"),
        );
        if (sections.length < 2) return;

        ScrollTrigger.create({
          snap: {
            snapTo: 1 / (sections.length - 1),
            duration: { min: 0.6, max: 0.8 },
            ease: "power2.inOut",
            directional: true,
          },
          start: "top top",
          end: () =>
            "+=" +
            (ref.current!.scrollHeight - window.innerHeight),
          scroller: undefined, // use window
        });
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
