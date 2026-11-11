import { walkthroughOn } from "@/app/sitemap";
import IvyFrame from "@/components/ivy/IvyFrame";

// How long the server's reading of the flag stands before it is asked again. The browser asks too (lib/useIvyMode) and its
// answer wins, so a flag turned on or off shows on the next read either way; this bounds how long the first paint can lag it.
const FLAG_SECONDS = 60;

/** Which Ivy to frame is read here, on the server, so the page arrives as the right one (components/ivy/IvyFrame). */
export default async function IvyLayout({ children }: { children: React.ReactNode }) {
  const walkthrough = await walkthroughOn(process.env.NEXT_PUBLIC_API_URL, fetch, FLAG_SECONDS);
  return <IvyFrame walkthrough={walkthrough}>{children}</IvyFrame>;
}
