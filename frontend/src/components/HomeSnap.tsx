"use client";

// The home page moves one section per gesture. Each .snap-section is one screen under the sticky header (from 640px up;
// globals.css html.home-snap). The browser's scroll snap (mandatory, snap-stop always) handles touch swipes and scrollbar drags.
// Wheel and keys are paged here, because Chrome returns a precise scroll shorter than half a screen to the section it started
// from, so a gentle trackpad step or one wheel notch would not move at all:
//   - a wheel gesture moves exactly one section; the trackpad's momentum events that follow are absorbed until the gesture ends
//     (no wheel event for GESTURE_GAP_MS after the move lands), so a long flick never carries past a section;
//   - inside a section taller than the screen (Browse the market) the wheel scrolls normally until that section's edge;
//   - PageDown, Space and ArrowDown move one section down; PageUp, Shift+Space and ArrowUp one up; Home and End go to the ends.
// It replaced StoryFlow's script-driven snap, which snapped only across its own five sections (its range ended at the last of
// them) and measured its stops once, so a flick from the first screen could carry past every stop to the bottom of the page.
import { useEffect } from "react";

const GESTURE_GAP_MS = 220;        // a quiet gap this long ends a wheel gesture (trackpad momentum included)
const MAX_LOCK_MS = 2500;          // a move never holds the page longer than this
const EDGE_PX = 2;

export function HomeSnap() {
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("home-snap");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const sections = () => [...document.querySelectorAll<HTMLElement>("main .snap-section")];
    const headerH = () => document.querySelector("header")?.getBoundingClientRect().height ?? 0;
    const maxY = () => root.scrollHeight - window.innerHeight;

    // each section's stop under the header, and for a section taller than the screen the stop that shows its bottom
    const layout = () => {
      const h = headerH(), view = window.innerHeight - h, max = maxY();
      return sections().map((el, i) => {
        const r = el.getBoundingClientRect();
        const top = i === 0 ? 0 : Math.min(max, Math.round(r.top + window.scrollY - h));
        return { top, bottom: Math.min(max, Math.round(top + r.height - view)), tall: r.height > view + EDGE_PX };
      });
    };
    // a section taller than the screen keeps native scrolling until its edge in the direction of travel
    const roomWithin = (dir: number) => {
      const h = headerH();
      const s = sections().find((el) => { const r = el.getBoundingClientRect(); return r.top <= h + EDGE_PX && r.bottom > h + EDGE_PX; });
      if (!s) return false;
      const r = s.getBoundingClientRect();
      if (r.height <= window.innerHeight - h + EDGE_PX) return false;
      return dir > 0 ? r.bottom > window.innerHeight + EDGE_PX : r.top < h - EDGE_PX;
    };

    let locked = false, lastWheel = 0, lockedAt = 0, target = 0, mode: "native" | "page" = "page";
    const moveTo = (y: number) => {
      target = y;
      locked = true; lockedAt = performance.now();
      window.scrollTo({ top: y, behavior: reduced ? "auto" : "smooth" });
    };
    // one section down: the next section's top (past the last, the page's end with the footer); one up: the previous section's
    // top, or its bottom when it is taller than the screen; from below a section's top (the footer), that section
    const go = (dir: number) => {
      const L = layout(), y = window.scrollY;
      let i = 0;
      L.forEach((sec, k) => { if (sec.top <= y + EDGE_PX) i = k; });
      let to: number;
      if (dir > 0) to = i + 1 < L.length ? L[i + 1].top : maxY();
      else if (y > L[i].top + EDGE_PX) to = L[i].tall ? L[i].bottom : L[i].top;
      else to = i > 0 ? (L[i - 1].tall ? L[i - 1].bottom : L[i - 1].top) : 0;
      if (dir < 0 && y > L[i].top + EDGE_PX && L[i].tall && Math.abs(y - L[i].bottom) <= EDGE_PX) to = L[i].top;
      if (Math.abs(to - y) > EDGE_PX) moveTo(to);
    };
    // a move ends once it has landed and the gesture behind it has gone quiet
    const release = window.setInterval(() => {
      if (!locked) return;
      const now = performance.now();
      const landed = Math.abs(window.scrollY - target) <= EDGE_PX || now - lockedAt > MAX_LOCK_MS;
      if (landed && now - lastWheel > GESTURE_GAP_MS) locked = false;
    }, 50);

    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || Math.abs(e.deltaY) < Math.abs(e.deltaX)) return;       // pinch zoom and sideways scrolls are not paging
      const dir = Math.sign(e.deltaY);
      if (!dir) return;
      const now = performance.now();
      const fresh = now - lastWheel > GESTURE_GAP_MS;
      lastWheel = now;
      if (fresh) mode = !locked && roomWithin(dir) ? "native" : "page";
      if (mode === "native") {                                                // a gesture that began inside a tall section
        if (!roomWithin(dir)) e.preventDefault();                             // stops at its edge; the next gesture moves on
        return;
      }
      e.preventDefault();
      if (!locked) go(dir);
    };
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(t.tagName))) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key;
      if (k === "Home" || k === "End") {
        e.preventDefault();
        moveTo(k === "Home" ? 0 : maxY());
        return;
      }
      const dir = k === "PageDown" || k === "ArrowDown" || (k === " " && !e.shiftKey) ? 1
        : k === "PageUp" || k === "ArrowUp" || (k === " " && e.shiftKey) ? -1 : 0;
      if (!dir || roomWithin(dir)) return;                                    // inside a tall section the keys scroll it
      e.preventDefault();
      if (!locked) go(dir);
    };
    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("keydown", onKey);
    return () => {
      root.classList.remove("home-snap");
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKey);
      window.clearInterval(release);
    };
  }, []);
  return null;
}
