// The company's short name for a title: the backend's rule (services/briefing.short_name) mirrored, kept equal by test.
// "Tesla" from "Tesla, Inc."; "JPMorgan Chase" from "JPMorgan Chase & Co."; "Home Depot" from "The Home Depot, Inc.".
export const NAME_SUFFIXES = ["incorporated", "inc", "corporation", "corp", "company", "co", "plc", "ltd", "limited", "holdings"];
export const TRAILING_WORDS = ["group", "companies"];

export function shortCompanyName(name: string | null | undefined, _symbol?: string): string | null {
  if (!name) return null;
  name = name.replace(/\s*\((?:The|HC)\)\s*$/, "")                                                  // "Goldman Sachs Group, Inc. (The)"
    .replace(/\s+(?:Class\s+[A-Z]\s+)?(?:Common\s+(?:Stock|Shares)|Ordinary\s+Shares)\s*$/i, "");    // "PepsiCo, Inc. Common Stock"
  const words = name.replace(/,/g, " ").split(/\s+/).filter(Boolean);
  while (words.length > 1 && NAME_SUFFIXES.includes(words[words.length - 1].toLowerCase().replace(/\.+$/, ""))) words.pop();
  if (words.length > 1 && words[0].toLowerCase() === "the") words.shift();
  while (words.length > 1 && TRAILING_WORDS.includes(words[words.length - 1].toLowerCase())) words.pop();
  while (words.length > 1 && (words[words.length - 1] === "&" || words[words.length - 1] === "and")) words.pop();
  return words.join(" ");
}
