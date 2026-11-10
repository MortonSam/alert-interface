"use client";

// Sign in with an email link, and the signed-in person's settings: each email on or off, sign out (here or everywhere), delete the
// account. Only while NEXT_PUBLIC_ACCOUNTS_ENABLED is "true"; reading the site never needs this page.
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ACCOUNTS_ON, account, moveLocalIntoAccount, type Me } from "@/lib/account";
import { ACCOUNT_COPY as C } from "@/lib/accountCopy";

function SignIn() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);
  if (state === "sent") {
    return (
      <section className="max-w-md">
        <h1 className="text-display font-display font-bold text-foreground">{C.checkEmailTitle}</h1>
        <p className="mt-3 text-foreground/85">{C.checkEmailBody(email)}</p>
      </section>
    );
  }
  return (
    <section className="max-w-md">
      <h1 className="text-display font-display font-bold text-foreground">{C.signInTitle}</h1>
      <p className="mt-3 text-foreground/85">{C.signInBody}</p>
      <form className="mt-6 space-y-3" onSubmit={async (e) => {
        e.preventDefault();
        setState("sending"); setError(null);
        const r = await account.signIn(email);
        if (r.ok) setState("sent"); else { setState("idle"); setError(r.detail); }
      }}>
        <label htmlFor="account-email" className="block text-sm text-muted-foreground">{C.emailLabel}</label>
        <input id="account-email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={C.emailPlaceholder}
          className="w-full rounded-lg border border-border bg-background px-3 py-2.5 max-sm:min-h-11 text-sm outline-none focus:border-foreground/40" />
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <button type="submit" disabled={state === "sending"} className="tap rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-60">
          {state === "sending" ? C.sending : C.sendLink}
        </button>
      </form>
    </section>
  );
}

function Settings({ me, setMe }: { me: Me; setMe: (m: Me | null) => void }) {
  const params = useSearchParams();
  const follow = params.get("follow");
  const followName = params.get("name") || follow;
  const [followed, setFollowed] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <section className="max-w-xl space-y-8">
      <div>
        <h1 className="text-display font-display font-bold text-foreground">{C.settingsTitle}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{C.signedInAs(me.email)}</p>
        {notice && <p className="mt-3 text-sm text-foreground/85" role="status">{notice}</p>}
      </div>
      {follow && followName && (
        <div className="rounded-xl border border-border p-4">
          <h2 className="text-headline font-display font-semibold">{C.followTitle(followName)}</h2>
          {followed ? <p className="mt-2 text-sm text-foreground/85">{C.followDone(followName)}</p> : (
            <>
              <p className="mt-2 text-sm text-foreground/85">{C.followBody(followName)}</p>
              <button type="button" className="tap mt-3 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground" onClick={async () => {
                await account.importLocal([follow]);
                const r = await account.setEmails({ earnings_eve: true });
                if (r.data) setMe(r.data);
                setFollowed(true);
              }}>{C.followConfirm}</button>
            </>
          )}
        </div>
      )}
      <div>
        <h2 className="text-headline font-display font-semibold">{C.emailsTitle}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{C.emailsBody}</p>
        {me.suppressed && <p className="mt-2 text-sm text-foreground" data-testid="email-suppressed">{me.suppressed}</p>}
        <ul className="mt-4 divide-y divide-border/60">
          {me.emails.map((e) => (
            <li key={e.kind} className="flex items-start justify-between gap-4 py-3">
              <div>
                <p className="text-sm font-medium">{e.name}</p>
                <p className="text-sm text-muted-foreground">{e.about}</p>
              </div>
              <button type="button" role="switch" aria-checked={e.enabled} className={`tap shrink-0 rounded-full border px-3 py-1 text-xs ${e.enabled ? "border-primary bg-primary/10" : "border-border"}`}
                onClick={async () => { const r = await account.setEmails({ [e.kind]: !e.enabled }); if (r.data) setMe(r.data); }}>
                {e.enabled ? C.on : C.off}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="tap rounded-lg border border-border px-4 py-2 text-sm" onClick={async () => { await account.signOut(); setMe(null); }}>{C.signOut}</button>
        <button type="button" className="tap rounded-lg border border-border px-4 py-2 text-sm" onClick={async () => { const r = await account.signOutEverywhere(); setNotice(r.detail); setMe(null); }}>{C.signOutEverywhere}</button>
      </div>
      <div className="rounded-xl border border-border p-4">
        <h2 className="text-headline font-display font-semibold">{C.deleteTitle}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{C.deleteBody}</p>
        {confirmDelete ? (
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" className="tap rounded-lg border border-destructive/60 px-4 py-2 text-sm" onClick={async () => { await account.remove(); setMe(null); setNotice(C.deleted); }}>{C.deleteConfirm}</button>
            <button type="button" className="tap rounded-lg border border-border px-4 py-2 text-sm" onClick={() => setConfirmDelete(false)}>{C.deleteCancel}</button>
          </div>
        ) : (
          <button type="button" className="tap mt-3 rounded-lg border border-border px-4 py-2 text-sm" onClick={() => setConfirmDelete(true)}>{C.deleteButton}</button>
        )}
      </div>
      <p className="text-sm text-muted-foreground"><Link href="/privacy" className="hover:text-foreground">{C.privacy}</Link> · <Link href="/terms" className="hover:text-foreground">{C.terms}</Link></p>
    </section>
  );
}

function AccountScreen() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => { account.me().then((r) => setMe(r.ok ? r.data : null)); }, []);
  useEffect(() => { if (me) moveLocalIntoAccount(); }, [me]);
  if (me === undefined) return null;
  return me ? <Settings me={me} setMe={setMe} /> : <SignIn />;
}

export default function AccountPage() {
  if (!ACCOUNTS_ON) return <main className="max-w-7xl mx-auto px-4 sm:px-8 py-10" />;
  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-8 py-10">
      <Suspense fallback={null}><AccountScreen /></Suspense>
    </main>
  );
}
