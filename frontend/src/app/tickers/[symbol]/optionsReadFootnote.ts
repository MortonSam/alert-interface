import type { OptionsRead } from "@/lib/api";

import { fmtDate as fmtOneDate } from "@/lib/dates";
/** The chain date shown under Ivy's Read. It comes from the chain or is omitted: never today's date. */
export function chainDateLabel(read: Pick<OptionsRead, "chain_date">): string {
  return read.chain_date ? ` · chain as of ${fmtOneDate(read.chain_date) ?? read.chain_date}` : "";
}
