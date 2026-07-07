#!/bin/sh
set -e

echo "[entrypoint] Running Alembic migrations …"
alembic upgrade head

echo "[entrypoint] Migrations complete — starting server …"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
