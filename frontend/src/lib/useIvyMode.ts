"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { fetchIvyPage, type IvyPage } from "@/lib/walkthrough";

/**
 * Which Ivy a visitor gets (Sam, 2026-11-10). The API serves /ivy-page only while IVY_WALKTHROUGH_ENABLED is on (or to the admin
 * token, the preview), so its answer is the flag: with an answer the one new page shows; without one (a 404, or a read that
 * failed) Meet Ivy, the Desk and the Trades stay as they were. One read per page load, shared by the layout and the page inside it.
 *
 * The server asks the same question when it renders the /ivy routes (app/ivy/layout) and hands its answer down through IvyFlag,
 * so the page is the right Ivy from the first paint (Sam, 2026-11-11). The browser's own answer replaces it once it is in: that
 * is what shows the preview to the admin token, and a flag changed since the server last asked.
 */
export type IvyMode = { mode: "loading" } | { mode: "old" } | { mode: "walkthrough" };

/** The flag as the server read it for this page; undefined outside the /ivy frame. */
export const IvyFlag = createContext<boolean | undefined>(undefined);

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

/** The browser's answer when it has one, the server's until then, and loading only where neither is known. */
export const ivyMode = (page: IvyPage | null | undefined, served?: boolean): IvyMode =>
  page !== undefined ? { mode: page ? "walkthrough" : "old" }
    : served === undefined ? { mode: "loading" } : { mode: served ? "walkthrough" : "old" };

let textAsked: Promise<IvyPage | null> | null = null;

/**
 * Whether text that differs with the walkthrough (lib/glossary, Sam 2026-11-11) reads its walkthrough form: by the server's answer
 * where the page hands one down (the /ivy frame, Disclosures), else by the browser's, asked once per page load and only when `ask`
 * (a tip whose term reads the same either way never asks). Off until an answer is in, as it is for the pages.
 */
export function useWalkthroughOn(ask: boolean): boolean {
  const served = useContext(IvyFlag);
  const [page, setPage] = useState<IvyPage | null | undefined>(settled);
  useEffect(() => {
    if (!ask || served !== undefined) return;
    let alive = true;
    (textAsked ??= readIvyPage()).then((p) => { if (alive) setPage(p); });
    return () => { alive = false; };
  }, [ask, served]);
  return ivyMode(page, served).mode === "walkthrough";
}

export function useIvyMode(): IvyMode {
  const served = useContext(IvyFlag);
  const [page, setPage] = useState<IvyPage | null | undefined>(settled);
  useEffect(() => {
    let alive = true;
    readIvyPage().then((p) => { if (alive) setPage(p); });
    return () => { alive = false; };
  }, []);
  return ivyMode(page, served);
}
