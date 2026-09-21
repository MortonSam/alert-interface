// Sections that are switched off because the data they need does not exist yet.
// Each flag names the condition that must become true before it is turned on.

/**
 * Discover's "Just reported" lists earnings reactions from the last 5 days. A
 * reaction row is only created once the event is 8 days old (MIN_AGE_DAYS in
 * seed_historical_reactions.py), so the section can never have a row.
 * Turn this on when the seeder writes a provisional 1-day row as soon as the
 * 1-day close exists.
 */
export const JUST_REPORTED_ENABLED = false;
