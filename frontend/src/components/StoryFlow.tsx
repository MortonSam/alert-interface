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

          // Snap targets as scroll progress. The hero snaps to 0; every later section snaps so its top sits just
          // under the sticky header (the sections after the hero are sized to the viewport minus that header).
          let snapPoints: number[] = [];
          // Progress of the last settled stop. One wheel gesture moves exactly one stop from here in the
          // direction of travel: GSAP's own `directional` option only applies to array targets, and its
          // inertia projection otherwise lands a trackpad flick on the nearest section, which can be two away.
          let anchor = 0;

          function headerOffset(): number {
            const header = document.querySelector("header");
            return header ? header.getBoundingClientRect().height : 0;
          }

          function measure(self: ScrollTrigger) {
            const range = self.end - self.start;
            if (range <= 0) return;
            const offset = headerOffset();
            const pts: number[] = [];

            sections.forEach((section, i) => {
              const pinST = ScrollTrigger.getAll().find(
                (t) => t.trigger === section && t.pin,
              );
              if (pinST) {
                pts.push((pinST.start - self.start) / range);
                pts.push((pinST.end - self.start) / range);
              } else {
                const absY =
                  section.getBoundingClientRect().top + window.scrollY - (i === 0 ? 0 : offset);
                pts.push((absY - self.start) / range);
              }
            });

            snapPoints = pts
              .map((p) => Math.max(0, Math.min(1, p)))
              .sort((a, b) => a - b);
            anchor = nearest(self.progress);
          }

          function nearest(progress: number): number {
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
          }

          // The next stop past `anchor` in the direction of travel. A scroll that already carried past that
          // stop (a scrollbar drag, a long flick) settles on the nearest stop instead of jumping back.
          function nextStop(progress: number, direction: number): number {
            const eps = 1e-4;
            const ahead = snapPoints.filter((p) =>
              direction < 0 ? p < anchor - eps : p > anchor + eps,
            );
            if (ahead.length === 0) return nearest(progress);
            const target = direction < 0 ? ahead[ahead.length - 1] : ahead[0];
            const passed = direction < 0 ? progress < target - eps : progress > target + eps;
            return passed ? nearest(progress) : target;
          }

          const trigger = ScrollTrigger.create({
            trigger: container,
            start: "top top",
            end: () =>
              "+=" + (container.scrollHeight - window.innerHeight),
            snap: {
              snapTo(_naturalEnd: number, self?: ScrollTrigger) {
                if (snapPoints.length === 0 || !self) return _naturalEnd;
                return nextStop(self.progress, self.direction);
              },
              duration: { min: 0.35, max: 0.7 },
              ease: "power2.inOut",
              inertia: false,
              delay: 0,
              onComplete(self) {
                anchor = nearest(self.progress);
              },
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
