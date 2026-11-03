// Email accounts (backend routers/accounts), only while NEXT_PUBLIC_ACCOUNTS_ENABLED is "true". The session is an HttpOnly cookie on
// this site's own origin (the /api rewrite), so the browser sends it and no script can read it. What a visitor saved in this browser
// before signing in (LOCAL_WATCHLIST_KEY) moves into the account on the first sign-in (importLocal) and is then cleared here.

export const ACCOUNTS_ON = process.env.NEXT_PUBLIC_ACCOUNTS_ENABLED === "true";
export const LOCAL_WATCHLIST_KEY = "local_watchlist";
export const ACCOUNT_MARKER_KEY = "account_signed_in";    // a hint for the page's sign-in checks (lib/session isSignedIn), never a credential
export const SIGN_IN_STATUS = 401;                        // the API's answer to a request that needs sign-in

function mark(on: boolean): void {
  try { if (on) localStorage.setItem(ACCOUNT_MARKER_KEY, "1"); else localStorage.removeItem(ACCOUNT_MARKER_KEY); } catch { /* private mode */ }
}
const BASE = "/api/v1/account";

export interface EmailKind { kind: string; name: string; about: string; enabled: boolean }
export interface Me { email: string; emails: EmailKind[]; watchlist_count: number; trade_count: number; suppressed?: string | null }   // suppressed: the API's sentence when Postmark stopped this address
export interface TradeResult {
  paid_usd: number; worth_usd: number; result_usd: number; result_pct: number | null; ahead: boolean;
  stock_move_pct: number | null; priced_move_pct: number | null; moved_vs_priced: "more" | "less" | "same" | null; expiration: string; saved_on: string;
}
export interface ResultItem { id: string; symbol: string; option_type: string; strike: number | null; strike2: number | null; expiration: string | null; saved_on: string; result: TradeResult | null }

async function call<T>(path: string, init?: RequestInit): Promise<{ ok: boolean; status: number; data: T | null; detail: string | null }> {
  const res = await fetch(`${BASE}${path}`, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...init });
  let body: unknown = null;
  try { body = await res.json(); } catch { body = null; }
  const detail = body && typeof body === "object" && "detail" in body ? String((body as { detail: unknown }).detail) : null;
  return { ok: res.ok, status: res.status, data: res.ok ? (body as T) : null, detail };
}

export const account = {
  me: async () => { const r = await call<Me>(""); if (r.status === SIGN_IN_STATUS || r.ok) mark(r.ok); return r; },
  signIn: (email: string) => call<{ detail: string }>("/sign-in", { method: "POST", body: JSON.stringify({ email }) }),
  verify: async (token: string) => { const r = await call<{ signed_in: boolean }>("/verify", { method: "POST", body: JSON.stringify({ token }) }); if (r.ok) mark(true); return r; },
  setEmails: (prefs: Record<string, boolean>) => call<Me>("/emails", { method: "PUT", body: JSON.stringify(prefs) }),
  importLocal: (watchlist: string[]) => call<{ watchlist_added: number }>("/import", { method: "POST", body: JSON.stringify({ watchlist, trades: [] }) }),
  signOut: () => { mark(false); return call<{ detail: string }>("/sign-out", { method: "POST" }); },
  signOutEverywhere: () => { mark(false); return call<{ detail: string }>("/sign-out-everywhere", { method: "POST" }); },
  remove: () => { mark(false); return call<{ detail: string }>("", { method: "DELETE" }); },
  results: () => call<{ label: string; summary: string | null; items: ResultItem[] }>("/trades/results"),
};

export function readLocalWatchlist(storage: Pick<Storage, "getItem"> | null = typeof window === "undefined" ? null : window.localStorage): string[] {
  try {
    const raw = storage?.getItem(LOCAL_WATCHLIST_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((s) => typeof s === "string").slice(0, 200) : [];
  } catch { return []; }
}

export function writeLocalWatchlist(symbols: string[], storage: Pick<Storage, "setItem" | "removeItem"> | null = typeof window === "undefined" ? null : window.localStorage): void {
  try {
    if (!symbols.length) storage?.removeItem(LOCAL_WATCHLIST_KEY);
    else storage?.setItem(LOCAL_WATCHLIST_KEY, JSON.stringify([...new Set(symbols)]));
  } catch { /* private mode: nothing kept, nothing lost */ }
}

/** The first sign-in on this browser: what it saved moves into the account, then leaves the browser. Returns how many moved in. */
export async function moveLocalIntoAccount(): Promise<number> {
  const symbols = readLocalWatchlist();
  if (!symbols.length) return 0;
  const r = await account.importLocal(symbols);
  if (r.ok) writeLocalWatchlist([]);
  return r.data?.watchlist_added ?? 0;
}
