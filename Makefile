.PHONY: up down logs shell db-shell migrate migration rollback seed seed-macro seed-reactions seed-sp500 seed-sp500-retry validate install run

# ── Docker ────────────────────────────────────────────────
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f backend

# ── Database ──────────────────────────────────────────────
migrate:
	docker compose exec backend alembic upgrade head

# Usage: make migration name="add_thesis_table"
migration:
	docker compose exec backend alembic revision --autogenerate -m "$(name)"

rollback:
	docker compose exec backend alembic downgrade -1

# Usage: make seed TICKER=AAPL  or  make seed TICKER="AAPL MSFT NVDA"
seed:
	docker compose exec backend python -m app.scripts.seed_ticker $(TICKER)

seed-macro:
	docker compose exec backend python -m app.scripts.seed_macro

# Usage: make seed-reactions TICKER=AAPL  or  make seed-reactions TICKER="AAPL MSFT NVDA"
seed-reactions:
	docker compose exec backend python -m app.scripts.seed_historical_reactions $(TICKER)

seed-sp500:
	docker compose exec backend python -m app.scripts.seed_sp500

seed-sp500-retry:
	docker compose exec backend python -m app.scripts.seed_sp500 --retry-only

validate:
	docker compose exec backend python -m app.scripts.validate_data

# ── Shells ────────────────────────────────────────────────
shell:
	docker compose exec backend bash

db-shell:
	docker compose exec db psql -U alert -d alertdb

# ── Local dev (no Docker) ─────────────────────────────────
install:
	pip install -r backend/requirements.txt

run:
	cd backend && uvicorn app.main:app --reload --port 8000
