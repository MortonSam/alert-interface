// Sections that are switched off because the data they need does not exist yet.
// Each flag names the condition that must become true before it is turned on.

/**
 * Discover's "Just reported" lists earnings reactions from the last 5 days. Until
 * 2026-10-29 a reaction row was only created once the event was 8 days old, so the
 * section could never have a row; the seeder now stores the first-day move the
 * night after the report's first session closes (MIN_AGE_DAYS 1 in
 * seed_historical_reactions.py). Turning the section on is a separate decision.
 */
export const JUST_REPORTED_ENABLED = false;
