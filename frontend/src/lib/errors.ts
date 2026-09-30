import { ApiError } from "./api";

/**
 * What a visitor reads when a request fails. The API writes its refusals as sentences for visitors
 * (a draft limit and when it lifts, owner-only generation, a ticker not found), so an ApiError's message
 * is shown as it came. Anything else (a network failure, a body that was not a sentence) shows the
 * caller's plain fallback: no exception text, no status code, no JSON reaches the page.
 */
export function visitorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.message && !/^API \d{3}/.test(err.message)) return err.message;
  return fallback;
}

export const DRAFT_FAILED = "The draft could not be generated just now. Try again in a minute.";
export const DESK_FAILED = "Ivy\u2019s desk could not be loaded just now. Try again in a minute.";
export const TRADES_FAILED = "Ivy\u2019s trades could not be loaded just now. Try again in a minute.";
export const ALTERNATIVE_FAILED = "An alternative could not be generated just now. Try again in a minute.";
export const SAVE_FAILED = "The trade could not be saved just now. Try again in a minute.";
