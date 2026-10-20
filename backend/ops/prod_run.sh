#!/bin/bash
# prod_run.sh <python -m args...>   A one-off job against production from the Mac, with production's own environment: every
# variable of the alert-interface service on Railway, read through `railway run --service alert-interface`, and so production's
# Anthropic key, never the dev .env. The database URL is the public proxy's (the service's own points at Railway's internal host,
# which the Mac cannot reach). services/prod_key_guard refuses a model call on production's database without this environment.
# Run from backend/ in the main checkout or a worktree; the current backend/ is mounted. Large writes still run on Railway itself
# (CLAUDE.md, Production Writes).
set -euo pipefail
cd "$(dirname "$0")/.."
PUB=$(railway variables --service Postgres --kv | sed -n 's/^DATABASE_PUBLIC_URL=//p')
[ -n "$PUB" ] || { echo "prod_run: could not read the Postgres public URL from Railway" >&2; exit 2; }
H=${PUB#postgresql://}
ENVF=$(mktemp); chmod 600 "$ENVF"; trap 'rm -f "$ENVF"' EXIT
# the service's variables (their names from Railway, their values as railway run supplies them; never printed), minus the database
# URLs replaced below
NAMES=$(railway variables --service alert-interface --kv | sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' | grep -vx 'DATABASE_URL\|DATABASE_URL_SYNC')
railway run --service alert-interface -- python3 -c '
import os, sys
for k in sys.argv[1:]:
    v = os.environ.get(k)
    if v is not None and "\n" not in v:
        print(f"{k}={v}")
' $NAMES > "$ENVF"
grep -q '^RAILWAY_ENVIRONMENT_NAME=production$' "$ENVF" || { echo "prod_run: railway run did not supply the production environment" >&2; exit 2; }
docker run --rm --env-file "$ENVF" -e PYTHONDONTWRITEBYTECODE=1 \
  -e DATABASE_URL="postgresql+asyncpg://$H" -e DATABASE_URL_SYNC="postgresql://$H" \
  -v "$PWD:/app" -w /app "${PROD_RUN_IMAGE:-alertgate-backend:2026-10-13}" "$@"
