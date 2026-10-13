"""Write tests/fixtures/validate_fixture.sql: a small data-only slice of a database (a few tickers and every row they touch) that the push
gate loads into alertdb_validate before running every validate check once, read only (scripts/validate_smoke). Read only on the source:
COPY (SELECT ...) TO STDOUT and nothing else.

    docker compose exec backend python -m app.scripts.build_validate_fixture [--source postgresql://alert:alert@db:5432/alertdb]

The slice keeps each check's queries reachable (delayed quotes, Intrinio chains, put/call rows, events of every type, bars, picks), so a
query that cannot run on Postgres raises here as it would in production. It is not a correctness fixture: results age with the clock.
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import psycopg2

SYMBOLS = ["SPY", "AAPL", "JPM", "NKE", "DECK", "MU", "APH"]     # the index, two picks (NKE, DECK), a split ticker (APH)
OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "validate_fixture.sql"
BARS_SINCE = "2024-01-01"
ANALYST_ACTION_DAYS = 365
CHAINS_PER_SYMBOL = 1
# never copied: people and what they typed or where they came from
SKIP = {"users", "watchlists", "watchlist_tickers", "ask_log", "finnhub_calls", "finnhub_calls_limiter_test"}
TICKER_IDS = "(SELECT id FROM tickers WHERE symbol = ANY(%(s)s))"
EVENTS = (f"(ticker_id IS NULL OR ticker_id IN {TICKER_IDS}) "
          f"AND (event_type <> 'analyst_action' OR event_date >= CURRENT_DATE - {ANALYST_ACTION_DAYS})")
SPECIAL = {
    "events": f"SELECT * FROM events WHERE {EVENTS}",
    "historical_reactions": f"SELECT * FROM historical_reactions WHERE ticker_id IN {TICKER_IDS} AND event_id IN (SELECT id FROM events WHERE {EVENTS})",
    "price_bars_shadow": f"SELECT * FROM price_bars_shadow WHERE symbol = ANY(%(s)s) AND date >= '{BARS_SINCE}'",
    "news_stories": "SELECT * FROM news_stories ORDER BY 1 DESC LIMIT 50",
}
# per-ticker keys are "<prefix>:<SYMBOL>..." (options_read:v3:SYM:date has the symbol third); IP-keyed rate limits are dropped
METADATA = """
WITH m AS (
    SELECT key, value, updated_at,
           CASE WHEN key ~ '^options_read:' THEN split_part(key, ':', 3) WHEN key ~ '^[a-z_]+:[A-Z]' THEN split_part(split_part(key, ':', 2), '|', 1) END AS sym,
           row_number() OVER (PARTITION BY split_part(key, ':', 1), split_part(key, ':', 2) ORDER BY key DESC) AS n
    FROM system_metadata WHERE key NOT LIKE '%%:ip:%%'
)
SELECT m.key,
       CASE WHEN m.key = 'live_quotes' THEN jsonb_set(m.value::jsonb, '{quotes}',
                COALESCE((SELECT jsonb_object_agg(k, v) FROM jsonb_each(m.value::jsonb -> 'quotes') q(k, v) WHERE k = ANY(%(s)s)), '{}'))::text
            ELSE m.value END AS value,
       m.updated_at
FROM m
WHERE m.sym IS NULL OR (m.sym = ANY(%(s)s) AND (m.key NOT LIKE 'intrinio_chain:%%' OR m.n <= """ + str(CHAINS_PER_SYMBOL) + """))
"""


def table_query(table: str, cols: list[str]) -> str | None:
    if table in SKIP or table == "alembic_version":      # alembic_version: the schema copy carries it
        return None
    if table == "system_metadata":
        assert cols == ["key", "value", "updated_at"], cols
        return METADATA
    if table in SPECIAL:
        return SPECIAL[table]
    if "symbol" in cols:
        return f"SELECT * FROM {table} WHERE symbol = ANY(%(s)s)"
    if "ticker_id" in cols:
        return f"SELECT * FROM {table} WHERE ticker_id IN {TICKER_IDS}"
    return f"SELECT * FROM {table}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="postgresql://alert:alert@db:5432/alertdb")
    args = ap.parse_args()
    conn = psycopg2.connect(args.source)
    conn.set_session(readonly=True)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1")
    tables = [r[0] for r in cur.fetchall()]
    out = io.StringIO()
    out.write("-- Written by app.scripts.build_validate_fixture; loaded by the push gate into alertdb_validate (data only).\n"
              "SET session_replication_role = replica;\n\n")
    counts = []
    for table in tables:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position", (table,))
        cols = [r[0] for r in cur.fetchall()]
        q = table_query(table, cols)
        if q is None:
            continue
        buf = io.StringIO()
        cur.copy_expert(f"COPY ({cur.mogrify(q, {'s': SYMBOLS}).decode()}) TO STDOUT", buf)
        body = buf.getvalue()
        n = body.count("\n")
        counts.append((table, n))
        if n:
            out.write(f'COPY public.{table} ({", ".join(chr(34) + c + chr(34) for c in cols)}) FROM stdin;\n{body}\\.\n\n')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out.getvalue())
    print(f"{OUT}: {OUT.stat().st_size / 1e6:.1f} MB, {sum(n for _, n in counts)} rows in {sum(1 for _, n in counts if n)} tables")


if __name__ == "__main__":
    main()
