"""Shared application constants."""

import os
from datetime import date

# No picks, evaluations, or stats from before this date are shown publicly.
LEDGER_START = date(2026, 9, 15)

# When false, public (anonymous) requests see empty ledger/activity.
# Admin-authenticated requests still see the full post-LEDGER_START record.
# Launch = set LEDGER_PUBLIC=true on Railway, redeploy.
LEDGER_PUBLIC = os.getenv("LEDGER_PUBLIC", "false").lower() in ("true", "1", "yes")

# Put/call ratio: minimum volume on each side to compute a ratio.
# If either put_total or call_total is below this, ratio is stored as NULL.
MIN_SIDE_CONTRACTS = 50

# Symbols whose yfinance price history predates the current listed entity
# (recycled symbol or merger). Reactions before these dates are not this company.
LISTING_DATE_OVERRIDES: dict[str, date] = {
    "SW": date(2024, 7, 8),    # Smurfit WestRock
    "TKO": date(2023, 9, 12),  # TKO Group Holdings
}
