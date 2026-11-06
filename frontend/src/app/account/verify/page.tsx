"use client";

// The sign-in link lands here: its token is in the fragment (#t=...), so it never reaches a server log or a referrer. It is sent once
// to the API, which sets the session cookie; what this browser saved before moves into the account.
import { useEffect, useState } from "react";
import Link from "next/link";
import { ACCOUNTS_ON, account, moveLocalIntoAccount } from "@/lib/account";
import { ACCOUNT_COPY as C } from "@/lib/accountCopy";

export default function VerifyPage() {
  const [state, setState] = useState<"working" | "ok" | "failed">("working");
  const [detail, setDetail] = useState<string | null>(null);
  const [moved, setMoved] = useState(0);
  useEffect(() => {
    if (!ACCOUNTS_ON) return;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("t");
    window.history.replaceState(null, "", window.location.pathname);          // the token leaves the address bar
    if (!token) { setState("failed"); return; }
    account.verify(token).then(async (r) => {
      if (!r.ok) { setState("failed"); setDetail(r.detail); return; }
      setMoved(await moveLocalIntoAccount());
      setState("ok");
    });
  }, []);
  if (!ACCOUNTS_ON) return <main className="max-w-7xl mx-auto px-4 sm:px-8 py-10" />;
  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-8 py-10">
      <section className="max-w-md">
        {state === "working" && <p className="text-foreground/85">{C.verifying}</p>}
        {state === "ok" && (
          <>
            <h1 className="text-display font-display font-bold text-foreground">{C.verified}</h1>
            {moved > 0 && <p className="mt-3 text-foreground/85">{C.movedIn(moved)}</p>}
            <p className="mt-4"><Link href="/account" className="text-primary">{C.settingsTitle} →</Link></p>
          </>
        )}
        {state === "failed" && (
          <>
            <h1 className="text-display font-display font-bold text-foreground">{C.verifyFailed}</h1>
            {detail && <p className="mt-3 text-foreground/85">{detail}</p>}
            <p className="mt-4"><Link href="/account" className="text-primary">{C.askNewLink} →</Link></p>
          </>
        )}
      </section>
    </main>
  );
}
