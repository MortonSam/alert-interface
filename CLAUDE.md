# Project Rules

## Frontend Dev Server

**Never run `npx next build` while the dev server (`next dev`) is running.** Both share the `.next` directory, and a concurrent build corrupts the dev server's webpack chunks, causing runtime TypeErrors. To validate:

- Use the dev server's own compile output (watch for "Compiled successfully" or errors in the terminal).
- If a production build is needed, stop the dev server first (`kill` the port 3000 process), then build, then restart.

## Backend Import Check

**After any backend edit, run `docker compose exec backend python -c "import app.main"` before committing.** Python syntax errors and decorator misordering only surface at import time. A bad push crashes production at boot with no fallback.

## Data Integrity Rule

Nothing wrong reaches the screen silently. Every displayed number must come from a stored, dated source (never a live fetch that can fail or return padded values); a missing value is shown as absent, never estimated; every metric has a sanity band enforced in validate_data; and any change to how a number is computed bumps the relevant version so history stays comparable.

Accepted exceptions: yfinance daily price history (chart candles, sparklines, reaction settlement). Everything else displayed must come from stored, dated sources.
