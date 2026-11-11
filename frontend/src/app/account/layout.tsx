import { notFound } from "next/navigation";
import { ACCOUNTS_ON } from "@/lib/account";

/** /account and /account/verify exist only while accounts are on; until then they are the site's not-found page (Sam, 2026-11-10). */
export default function AccountLayout({ children }: { children: React.ReactNode }) {
  if (!ACCOUNTS_ON) notFound();
  return <>{children}</>;
}
