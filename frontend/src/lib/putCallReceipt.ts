// The put/call row's receipt (compute_put_call version 4 sums every stored expiration of the chain's date and names them):
// "volume across the Oct 16, Oct 23 and Nov 20, 2026 expirations, as of Oct 14, 2026". A version-3 row, with only the nearest
// expiration on file, keeps its old receipt "volume, exp Oct 16, 2026, as of Oct 14, 2026". Dates go through lib/dates.
import { fmtDate } from "@/lib/dates";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function andList(xs: string[]): string {
  return xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

/** "Oct 16, Oct 23 and Nov 20, 2026", or across a year "Dec 18, 2026 and Jan 15, 2027": each year's dates, then that year. */
export function expirationList(isoDates: string[]): string {
  const byYear = new Map<string, string[]>();
  for (const d of [...isoDates].sort()) {
    const [y, m, day] = d.split("T")[0].split("-");
    byYear.set(y, [...(byYear.get(y) ?? []), `${MONTHS[Number(m) - 1]} ${Number(day)}`]);
  }
  return andList([...byYear.entries()].map(([y, ds]) => `${andList(ds)}, ${y}`));
}

export function putCallReceipt(pc: { expiration_used: string | null; expirations_used?: string[] | null; snapshot_date: string | null }): string | null {
  const asOf = pc.snapshot_date ? `, as of ${fmtDate(pc.snapshot_date) ?? pc.snapshot_date}` : "";
  const exps = pc.expirations_used ?? [];
  if (exps.length > 1) return `volume across the ${expirationList(exps)} expirations${asOf}`;
  if (exps.length === 1) return `volume, the ${expirationList(exps)} expiration${asOf}`;
  return pc.expiration_used ? `volume, exp ${fmtDate(pc.expiration_used) ?? pc.expiration_used}${asOf}` : null;
}
