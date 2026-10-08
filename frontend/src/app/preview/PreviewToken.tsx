"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const KEY = "admin_token";

function read(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export default function PreviewToken() {
  const [saved, setSaved] = useState<boolean | null>(null);
  const [value, setValue] = useState("");
  useEffect(() => {
    // a token in the link's fragment (#t=...) is never sent to the server; it is stored and then wiped from the address bar
    const m = window.location.hash.match(/(?:^#|&)t=([^&]+)/);
    if (m) {
      try { localStorage.setItem(KEY, decodeURIComponent(m[1])); } catch {}
      history.replaceState(null, "", window.location.pathname);
    }
    setSaved(!!read());
  }, []);

  const save = () => {
    const t = value.trim();
    if (!t) return;
    try { localStorage.setItem(KEY, t); } catch {}
    setValue("");
    setSaved(!!read());
  };
  const clear = () => {
    try { localStorage.removeItem(KEY); } catch {}
    setSaved(!!read());
  };

  return (
    <div className="space-y-5">
      <h1 className="font-display text-2xl font-bold">Preview</h1>
      <p className="text-sm text-muted-foreground" data-testid="preview-state">
        {saved === null ? "" : saved ? "Preview is on in this browser." : "Preview is off in this browser."}
      </p>
      <label className="block text-sm">
        <span className="text-muted-foreground">Admin token</span>
        <input
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2.5 text-base"
        />
      </label>
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={save} className="min-h-[44px] rounded-xl bg-primary text-primary-foreground px-5 text-sm font-semibold">Save</button>
        <button type="button" onClick={clear} className="min-h-[44px] rounded-xl border border-border px-5 text-sm">Clear</button>
        <Link href="/discover" className="min-h-[44px] inline-flex items-center rounded-xl border border-border px-5 text-sm">Open Discover</Link>
      </div>
    </div>
  );
}
