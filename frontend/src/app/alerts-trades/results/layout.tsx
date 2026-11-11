import { notFound } from "next/navigation";
import { ACCOUNTS_ON } from "@/lib/account";

/** Hypothetical results belong to an account; while accounts are off this is the site's not-found page (Sam, 2026-11-10). */
export default function ResultsLayout({ children }: { children: React.ReactNode }) {
  if (!ACCOUNTS_ON) notFound();
  return <>{children}</>;
}
