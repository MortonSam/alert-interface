import { shortCompanyName } from "@/lib/companyName";

export const SITE_NAME = "Alert Interface";

/** "Tesla (TSLA) earnings, options and research | Alert Interface" (Sam's form, 2026-10-12); the symbol alone without a company record. */
export function tickerTitle(symbol: string, name: string | null | undefined): string {
  const short = name ? shortCompanyName(name, symbol) : null;
  const subject = short ? `${short} (${symbol})` : symbol;
  return `${subject} earnings, options and research | ${SITE_NAME}`;
}
