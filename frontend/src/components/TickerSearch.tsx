"use client";

// The ticker search box: in the header on every page, and at the top of the home page. Symbol or company
// name, the same matcher as Build a Trade (lib/tickerSearch); Enter or a click opens /tickers/SYMBOL.
// In the header at phone width it collapses to an icon that opens the box.

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Ticker } from "@/lib/api";
import { matchTickers, tickerPath } from "@/lib/tickerSearch";

export const HOME_SEARCH_LABEL = "Look up a stock";
/** Tailwind's sm breakpoint, the one the header collapses at: the home box takes focus on load only from here up. */
export const DESKTOP_QUERY = "(min-width: 640px)";
export const SEARCH_PLACEHOLDER = "Symbol or company name";

let cached: Promise<Ticker[]> | null = null;
/** The active ticker list, fetched once per page load and shared by every box on the page. */
function tickerList(): Promise<Ticker[]> {
  if (!cached) cached = api.tickers.list().catch(() => { cached = null; return []; });
  return cached;
}

function SearchBox({ inputClassName, autoFocus, label, onNavigate }: {
  inputClassName: string;
  autoFocus?: boolean | "desktop";   // "desktop": focus on load only from the sm breakpoint up, so a phone keyboard never opens over the page
  label?: string;
  onNavigate?: () => void;
}) {
  const router = useRouter();
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [tickers, setTickers] = useState<Ticker[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  function load() {
    if (tickers === null) tickerList().then(setTickers);
  }
  useEffect(() => {
    if (!autoFocus) return;
    if (autoFocus === "desktop" && !window.matchMedia(DESKTOP_QUERY).matches) return;
    inputRef.current?.focus();
    load();
  }, [autoFocus]);   // eslint-disable-line react-hooks/exhaustive-deps

  const matches = useMemo(() => matchTickers(tickers ?? [], query), [tickers, query]);

  function go(path: string | null) {
    if (!path) return;
    setQuery("");
    setOpen(false);
    onNavigate?.();
    router.push(path);
  }

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  return (
    <div ref={containerRef} className="relative w-full">
      {label && <label htmlFor={id} className="block font-mono text-xs uppercase tracking-[.16em] text-primary mb-2">{label}</label>}
      <input
        ref={inputRef}
        id={id}
        type="search"
        role="combobox"
        aria-expanded={open && matches.length > 0}
        aria-autocomplete="list"
        aria-label={label ?? "Search tickers"}
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); load(); }}
        onFocus={() => { setOpen(true); load(); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); go(tickerPath(matches)); }
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder={SEARCH_PLACEHOLDER}
        className={inputClassName}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
      />
      {open && query.trim() && matches.length > 0 && (
        <div role="listbox" className="absolute left-0 right-0 top-full mt-1 z-50 rounded-xl border bg-popover shadow-lg overflow-hidden">
          {matches.map((t) => (
            <button
              key={t.id}
              type="button"
              role="option"
              aria-selected={false}
              onMouseDown={(e) => { e.preventDefault(); go(`/tickers/${t.symbol}`); }}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-accent transition-colors"
            >
              <span className="font-bold text-sm w-14 shrink-0 tabular-nums">{t.symbol}</span>
              <span className="text-sm text-muted-foreground flex-1 truncate">{t.name}</span>
            </button>
          ))}
        </div>
      )}
      {open && query.trim() && tickers !== null && matches.length === 0 && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 rounded-xl border bg-popover shadow-lg px-4 py-3 text-sm text-muted-foreground">
          No tickers match &ldquo;{query}&rdquo;
        </div>
      )}
    </div>
  );
}

/** The header box: an input from sm up; at phone width an icon that opens the box on its own row. */
export function HeaderTickerSearch() {
  const [openOnPhone, setOpenOnPhone] = useState(false);
  return (
    <>
      <div className="hidden sm:block ml-auto w-56">
        <SearchBox inputClassName="w-full h-8 rounded-lg border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
      </div>
      <button
        type="button"
        aria-label={openOnPhone ? "Close ticker search" : "Search tickers"}
        aria-expanded={openOnPhone}
        onClick={() => setOpenOnPhone((v) => !v)}
        className="sm:hidden ml-auto p-1.5 rounded-md text-muted-foreground hover:text-foreground"
        data-testid="header-search-toggle"
      >
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
        </svg>
      </button>
      {openOnPhone && (
        <div className="sm:hidden basis-full pb-1">
          <SearchBox autoFocus onNavigate={() => setOpenOnPhone(false)}
            inputClassName="w-full h-9 rounded-lg border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
        </div>
      )}
    </>
  );
}

/** The home page box: labelled, above the copy, focused on load from the sm breakpoint up. */
export function HomeTickerSearch() {
  return (
    <div className="w-full max-w-md mx-auto" data-testid="home-search">
      <SearchBox autoFocus="desktop" label={HOME_SEARCH_LABEL}
        inputClassName="w-full h-12 rounded-xl border bg-background px-4 text-base placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
    </div>
  );
}
