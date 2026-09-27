import Link from "next/link";

/** The signed-out state of a personal-data view: a title, why, and the open path. No rows, no controls. */
export default function SignedOutNotice({
  title,
  body,
  openPath,
}: {
  title: string;
  body: string;
  openPath?: { href: string; label: string };
}) {
  return (
    <section
      data-testid="signed-out-notice"
      className="rounded-xl border border-border/60 px-6 py-8 text-center space-y-3"
    >
      <h2 className="text-lg font-display font-semibold">{title}</h2>
      <p className="text-sm text-muted-foreground max-w-prose mx-auto">{body}</p>
      {openPath && (
        <Link href={openPath.href} className="inline-block text-sm text-primary hover:text-primary/80">
          {openPath.label}
        </Link>
      )}
    </section>
  );
}
