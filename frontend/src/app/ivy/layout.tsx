// The one Ivy page's frame (Sam, 2026-11-02): Ivy's Desk and Ivy's Trades are gone, so there are no tabs.
export default function IvyLayout({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-5xl px-4">{children}</div>;
}
