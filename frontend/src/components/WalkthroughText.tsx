"use client";

import { IvyFlag } from "@/lib/useIvyMode";

/** Hands a server page's reading of the walkthrough flag to the glossary terms inside it (lib/glossary explanationOf), so a page
 *  whose sentences were chosen by that reading explains its terms by the same one. */
export default function WalkthroughText({ on, children }: { on: boolean; children: React.ReactNode }) {
  return <IvyFlag.Provider value={on}>{children}</IvyFlag.Provider>;
}
