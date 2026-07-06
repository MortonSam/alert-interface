"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export default function Tip({
  children,
  text,
}: {
  children: React.ReactNode;
  text: string;
}) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const ref = useRef<HTMLSpanElement>(null);

  function show() {
    if (ref.current) setRect(ref.current.getBoundingClientRect());
  }
  function hide() {
    setRect(null);
  }

  // Dismiss on outside tap (mobile)
  useEffect(() => {
    if (!rect) return;
    function onTouch(e: TouchEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setRect(null);
      }
    }
    document.addEventListener("touchstart", onTouch);
    return () => document.removeEventListener("touchstart", onTouch);
  }, [rect]);

  return (
    <>
      <span
        ref={ref}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onTouchEnd={(e) => {
          e.preventDefault();
          rect ? hide() : show();
        }}
        tabIndex={0}
        className="inline-flex items-center cursor-help"
      >
        {children}
      </span>
      {rect &&
        createPortal(
          <div
            role="tooltip"
            style={{
              position: "fixed",
              top: rect.top - 8,
              left: Math.max(
                8,
                Math.min(
                  (typeof window !== "undefined" ? window.innerWidth : 1200) -
                    248,
                  rect.left + rect.width / 2 - 120,
                ),
              ),
              transform: "translateY(-100%)",
              zIndex: 9999,
            }}
            className="w-60 rounded-md border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-xl pointer-events-none whitespace-normal leading-relaxed"
          >
            {text}
          </div>,
          document.body,
        )}
    </>
  );
}
