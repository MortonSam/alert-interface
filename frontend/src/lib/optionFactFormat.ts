// The rows beside Ivy's Read render the read's fact block with the same
// formatting the backend's format_facts used for the prose (options_read_gate):
// dollars to 2 decimals, percents to 1 decimal, ranges "$lo - $hi". A strike
// printed to the whole dollar in a row while the prose said "$412.50" is the
// disagreement this file exists to prevent.

export function fmtDollars(x: number | null | undefined): string | null {
  return x == null ? null : `$${x.toFixed(2)}`;
}

/** "±8.3%" from a 0-1 decimal. */
export function fmtMovePct(x: number | null | undefined): string | null {
  return x == null ? null : `\u00B1${(x * 100).toFixed(1)}%`;
}

/** "±$28.08". */
export function fmtMoveDollars(x: number | null | undefined): string | null {
  return x == null ? null : `\u00B1${fmtDollars(x)}`;
}

/** "$384.42 - $440.58". */
export function fmtRange(lo: number | null | undefined, hi: number | null | undefined): string | null {
  return lo == null || hi == null ? null : `${fmtDollars(lo)} - ${fmtDollars(hi)}`;
}

/** Every number the rows print, from one fact block, formatted as the prose was. */
export function rowStrings(v: {
  atm_strike: number | null; expected_move_pct: number | null; expected_move_dollars: number | null;
  implied_range_low: number | null; implied_range_high: number | null;
}): { atm_strike: string | null; expected_move_pct: string | null; expected_move_dollars: string | null; implied_range: string | null } {
  return {
    atm_strike: fmtDollars(v.atm_strike),
    expected_move_pct: fmtMovePct(v.expected_move_pct),
    expected_move_dollars: fmtMoveDollars(v.expected_move_dollars),
    implied_range: fmtRange(v.implied_range_low, v.implied_range_high),
  };
}
