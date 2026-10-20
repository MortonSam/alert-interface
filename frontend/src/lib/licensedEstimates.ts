// Backend LICENSED_ESTIMATES (services/licensed_estimates): off, the API withholds every estimate, beat, miss, surprise and beat
// rate and sends `licensed_estimates: false` with the reported EPS against the same quarter a year earlier (eps_line) instead.
// Nothing on the site shows an estimate, a beat, a miss, a surprise or a beat rate (Block 2, 2026-10-20): the pages never show
// them whatever the response says, so an older or cached response carrying them shows the year-ago line instead.
export function estimatesShown(_x: { licensed_estimates?: boolean } | null | undefined): boolean {
  return false;
}

export const YEAR_AGO_COLUMN = "EPS against a year earlier";
export const YEAR_AGO_COLUMN_TIP = "Reported EPS from SEC filings against the same quarter a year earlier. The stock's move is in the 1d, 3d and 5d columns, not here.";

// A REIT's rows carry measure "FFO per share" (backend services/ffo): FFO per diluted share from the earnings release, against the
// same quarter a year earlier. The column and its tip follow the rows' measure.
export const FFO_MEASURE = "FFO per share";
export const FFO_YEAR_AGO_COLUMN = "FFO per share against a year earlier";
export const FFO_YEAR_AGO_COLUMN_TIP = "FFO per diluted share as the earnings release states it, checked against the company's SEC filings, against the same quarter a year earlier. REITs report FFO because depreciation and property sales swing their EPS. The stock's move is in the 1d, 3d and 5d columns, not here.";

export function yearAgoColumn(rows: readonly { measure?: string | null }[] | null | undefined): { label: string; tip: string } {
  return rows?.some((r) => r.measure === FFO_MEASURE)
    ? { label: FFO_YEAR_AGO_COLUMN, tip: FFO_YEAR_AGO_COLUMN_TIP }
    : { label: YEAR_AGO_COLUMN, tip: YEAR_AGO_COLUMN_TIP };
}
