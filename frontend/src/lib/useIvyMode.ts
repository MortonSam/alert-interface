"use client";

import { useEffect, useState } from "react";
import { fetchIvyPage, type IvyPage } from "@/lib/walkthrough";

/**
 * Which Ivy a visitor gets (Sam, 2026-11-10). The API serves /ivy-page only while IVY_WALKTHROUGH_ENABLED is on (or to the admin
 * token, the preview), so its answer is the flag: with an answer the one new page shows; without one (a 404, or a read that
 * failed) Meet Ivy, the Desk and the Trades stay as they were. One read per page load, shared by the layout and the page inside it.
 */
export type IvyMode = { mode: "loading" } | { mode: "old" } | { mode: "walkthrough"; page: IvyPage };

let settled: IvyPage | null | undefined;
let pending: Promise<IvyPage | null> | null = null;

export function readIvyPage(): Promise<IvyPage | null> {
  pending ??= fetchIvyPage().then((page) => {
    settled = page;
    if (!page) pending = null;       // a read that failed is asked again by the next page
    return page;
  });
  return pending;
}

export const ivyMode = (page: IvyPage | null | undefined): IvyMode =>
  page === undefined ? { mode: "loading" } : page ? { mode: "walkthrough", page } : { mode: "old" };

export function useIvyMode(): IvyMode {
  const [page, setPage] = useState<IvyPage | null | undefined>(settled);
  useEffect(() => {
    let alive = true;
    readIvyPage().then((p) => { if (alive) setPage(p); });
    return () => { alive = false; };
  }, []);
  return ivyMode(page);
}
