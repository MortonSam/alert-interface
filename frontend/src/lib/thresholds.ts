/**
 * Mirror of backend/app/thresholds.py.
 *
 * These values MUST match the backend. A backend test
 * (tests/test_threshold_sync.py) reads this file and asserts
 * every value matches. Do not edit one without the other.
 */

// ── RV rank ────────────────────────────────────────────────────────
export const RV_RANK_EXTREME = 90;
export const RV_RANK_ELEVATED = 70;
export const RV_RANK_NORMAL = 25;

// ── IV-RV spread (ticker page) ─────────────────────────────────────
export const SPREAD_RICH_PP = 10;
export const SPREAD_CHEAP_PP = -10;

// ── IV-RV spread (discover page vol regime) ────────────────────────
export const DISCOVER_IV_RICH_PP = 8;
export const DISCOVER_IV_CHEAP_PP = -4;

// ── Put/call ratio ─────────────────────────────────────────────────
export const PC_PUT_HEAVY = 1.2;
export const PC_CALL_HEAVY = 0.7;

// ── Priced-in (beat-but-dropped rate) ──────────────────────────────
export const PRICED_IN_LARGELY = 50;
export const PRICED_IN_PARTIALLY = 25;

// ── EPS surprise display ───────────────────────────────────────────
export const EPS_SURPRISE_DOLLAR_FLOOR = 0.10;   // |estimate| below this: show the surprise in dollars
export const EPS_SURPRISE_PCT_CAP = 999;         // displayed percent is capped at +/- this

// ── Magnitude trend ────────────────────────────────────────────────
export const MAGNITUDE_INCREASE_THRESHOLD = 0.20;
export const MAGNITUDE_DECREASE_THRESHOLD = -0.20;

// ── Discover unusually-active tier ─────────────────────────────────
export const DISCOVER_EXTREME_RV = 93;
export const DISCOVER_ELEVATED_RV = 85;
