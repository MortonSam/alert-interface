/**
 * Sign-in state for the views that hold personal data: My Trades, Watchlists and
 * saving a thesis from Build a Trade.
 *
 * Sign-in on this site is the admin token stored as `admin_token` in localStorage;
 * the API client sends it as X-Admin-Token and the backend attributes the request
 * to admin-local only when it matches. There is no public sign-in flow: saving is in
 * private beta. Without the token the backend answers 401 to every personal read and
 * every write, and these views show the notice below instead of rows or controls.
 */
export const ADMIN_TOKEN_KEY = "admin_token";

export function isSignedIn(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return !!localStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return false;
  }
}

export const NO_PUBLIC_SIGN_IN =
  "Saving is in private beta, so there is no public sign-in yet.";

export const SIGN_IN_PROMPT = {
  title: "Sign in to see your trades",
  body: `My Trades shows the trades saved by the signed-in account, and this browser is not signed in. ${NO_PUBLIC_SIGN_IN} Building and previewing a trade are open to everyone.`,
};

export const WATCHLISTS_SIGN_IN_PROMPT = {
  title: "Sign in to see your watchlists",
  body: `Watchlists belong to the signed-in account, and this browser is not signed in. ${NO_PUBLIC_SIGN_IN}`,
};

export const SAVE_REQUIRES_SIGN_IN =
  `Saving needs a signed-in account, and this browser is not signed in: this trade can be built and previewed but not saved. ${NO_PUBLIC_SIGN_IN}`;

/** What the My Trades page shows. Signed out wins over everything: no rows, no controls, no counts. */
export type MyTradesView = "signed_out" | "loading" | "empty" | "rows";

export function myTradesView(signedIn: boolean, loading: boolean, rowCount: number): MyTradesView {
  if (!signedIn) return "signed_out";
  if (loading) return "loading";
  return rowCount === 0 ? "empty" : "rows";
}
