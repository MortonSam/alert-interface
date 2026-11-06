// The one kind of sign-in prompt the site shows (Sam, 2026-10-29): a quiet line where an unlocked feature is, with a link to the
// sign-in page. Never a pop-up, a wall or a countdown, and only while NEXT_PUBLIC_ACCOUNTS_ENABLED is "true".
import Link from "next/link";
import { ACCOUNTS_ON } from "@/lib/account";
import { ACCOUNT_COPY as C } from "@/lib/accountCopy";

export default function AccountPrompt({ text, href = "/account", testId }: { text: string; href?: string; testId?: string }) {
  if (!ACCOUNTS_ON) return null;
  return (
    <p className="text-sm text-muted-foreground" data-testid={testId}>
      {text} <Link href={href} className="text-primary hover:text-foreground">{C.signInLink} →</Link>
    </p>
  );
}
