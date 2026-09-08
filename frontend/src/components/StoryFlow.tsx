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
            // If this section owns a pinning ScrollTrigger, snap to
            // its pin-start and pin-end so the scrub settles at
            // exactly 0 ($30,000) or 1 ($0), never mid-count.
            const pinST = ScrollTrigger.getAll().find(
              (t) => t.trigger === section && t.pin,
            );
            if (pinST) {
              pts.push((pinST.start - self.start) / range);
              pts.push((pinST.end - self.start) / range);
            } else {
              // Absolute Y of the section in the document, converted
              // to progress within this trigger's range.
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

        // Refresh after all child ScrollTriggers (CostSection pin) exist
        requestAnimationFrame(() => {
          ScrollTrigger.refresh();
          measure(trigger);
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
