.PHONY: up down logs shell db-shell migrate migration rollback seed seed-macro seed-reactions seed-reactions-all seed-reactions-retry seed-sp500 seed-sp500-retry seed-sp500-force validate research-stats refresh enrich-revenue seed-splits seed-analyst-actions compute-analyst-reactions audit close-picks install run

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

seed-reactions-all:
	docker compose exec backend python -m app.scripts.seed_historical_reactions --all

seed-reactions-retry:
	docker compose exec backend python -m app.scripts.seed_historical_reactions --retry-only

seed-reactions-force:
	docker compose exec backend python -m app.scripts.seed_historical_reactions --all --force

seed-sp500:
	docker compose exec backend python -m app.scripts.seed_sp500

seed-sp500-retry:
	docker compose exec backend python -m app.scripts.seed_sp500 --retry-only

seed-sp500-force:
	docker compose exec backend python -m app.scripts.seed_sp500 --force-update

validate:
	docker compose exec backend python -m app.scripts.validate_data

refresh:
	docker compose exec backend python -m app.scripts.refresh

enrich-revenue:
	docker compose exec backend python -m app.scripts.enrich_revenue

seed-splits:
	docker compose exec backend python -m app.scripts.seed_splits

seed-analyst-actions:
	docker compose exec backend python -m app.scripts.seed_analyst_actions

compute-analyst-reactions:
	docker compose exec backend python -m app.scripts.compute_analyst_reactions

audit:
	docker compose exec backend python -m app.scripts.audit_sp500

close-picks:
	docker compose exec backend python -m app.scripts.close_alert_picks

research-stats:
	docker compose exec db psql -U alert -d alertdb -c \
	"SELECT t.symbol, rn.model_used, rn.input_tokens, rn.output_tokens, \
	 rn.input_tokens + rn.output_tokens AS total_tokens, rn.generated_at \
	 FROM research_notes rn JOIN tickers t ON t.id = rn.ticker_id \
	 ORDER BY rn.generated_at DESC;"

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
