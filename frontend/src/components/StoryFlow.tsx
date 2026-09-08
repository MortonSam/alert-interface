"use client";

import { useRef, type ReactNode } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);
ScrollTrigger.config({ ignoreMobileResize: true });

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

      // Desktop only: snap requires a precise pointer (no touch momentum fights)
      mm.add(
        "(prefers-reduced-motion: no-preference) and (pointer: fine)",
        () => {
          const container = ref.current!;
          const sections = gsap.utils.toArray<HTMLElement>(
            container.querySelectorAll(":scope > section"),
          );
          if (sections.length < 2) return;

          let snapPoints: number[] = [];

          function measure(self: ScrollTrigger) {
            const range = self.end - self.start;
            if (range <= 0) return;
            const pts: number[] = [];

            for (const section of sections) {
              const pinST = ScrollTrigger.getAll().find(
                (t) => t.trigger === section && t.pin,
              );
              if (pinST) {
                pts.push((pinST.start - self.start) / range);
                pts.push((pinST.end - self.start) / range);
              } else {
                const absY =
                  section.getBoundingClientRect().top + window.scrollY;
                pts.push((absY - self.start) / range);
              }
            }

            snapPoints = pts
              .map((p) => Math.max(0, Math.min(1, p)))
              .sort((a, b) => a - b);
          }

          const trigger = ScrollTrigger.create({
            trigger: container,
            start: "top top",
            end: () =>
              "+=" + (container.scrollHeight - window.innerHeight),
            snap: {
              snapTo(progress: number) {
                if (snapPoints.length === 0) return progress;
                let best = snapPoints[0];
                let bestDist = Math.abs(progress - best);
                for (let i = 1; i < snapPoints.length; i++) {
                  const d = Math.abs(progress - snapPoints[i]);
                  if (d < bestDist) {
                    bestDist = d;
                    best = snapPoints[i];
                  }
                }
                return best;
              },
              duration: { min: 0.35, max: 0.7 },
              ease: "power2.inOut",
              directional: true,
              delay: 0,
            },
            invalidateOnRefresh: true,
            onRefresh(self) {
              measure(self);
            },
          });

          requestAnimationFrame(() => {
            ScrollTrigger.refresh();
            measure(trigger);
          });
        },
      );
    },
    { scope: ref },
  );

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
