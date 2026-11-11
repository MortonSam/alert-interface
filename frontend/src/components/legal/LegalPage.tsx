// A legal draft (lib/legalDrafts), rendered only while NEXT_PUBLIC_ACCOUNTS_ENABLED is "true", with its draft status shown on the page;
// until then /privacy and /terms are the site's not-found page (Sam, 2026-11-10).
import { notFound } from "next/navigation";
import { ACCOUNTS_ON } from "@/lib/account";
import type { LegalDoc } from "@/lib/legalDrafts";

export default function LegalPage({ doc }: { doc: LegalDoc }) {
  if (!ACCOUNTS_ON) notFound();
  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-8 py-10">
      <p className="font-mono text-xs uppercase tracking-[.16em] text-primary">{doc.status}</p>
      <h1 className="mt-2 text-display font-display font-bold text-foreground">{doc.title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{doc.updated}</p>
      {doc.sections.map((s) => (
        <section key={s.heading} className="mt-8">
          <h2 className="text-headline font-display font-semibold">{s.heading}</h2>
          {s.paragraphs.map((p) => <p key={p} className="mt-2 text-foreground/85 leading-relaxed">{p}</p>)}
        </section>
      ))}
    </main>
  );
}
