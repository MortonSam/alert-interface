// Backend LICENSED_ESTIMATES (services/licensed_estimates): off, the API withholds every estimate, beat, miss, surprise and beat
// rate and sends `licensed_estimates: false` with the reported EPS against the same quarter a year earlier (eps_line) instead.
// A response from before the setting existed carries no flag and shows the estimates as it always did.
export function estimatesShown(x: { licensed_estimates?: boolean } | null | undefined): boolean {
  return x?.licensed_estimates !== false;
}

export const YEAR_AGO_COLUMN = "EPS against a year earlier";
export const YEAR_AGO_COLUMN_TIP = "Reported EPS from SEC filings against the same quarter a year earlier. The stock's move is in the 1d, 3d and 5d columns, not here.";
