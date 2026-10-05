"""A ticker changes symbol in place: same id, same history, an alias for the old symbol.

Intrinio keeps the security record (and its FIGI) across a rename, so the records build detects one when a record it
already holds comes back under a new ticker (EQR's record sec_gkDL4Q became VMRK). Every table that carries the
symbol is found from the catalogue, not from a list someone must remember to extend; system_metadata keys that
name the symbol as a segment (chain:EQR:..., options_read:v4:EQR:...) are rewritten too.

When the new symbol already exists as its own ticker row for the same Intrinio security (the constituent scrape
seeded VMRK in August while EQR kept the history), that younger duplicate is absorbed first: on every table its rows
move to the old ticker, except where the old ticker already holds the same key, and then the old ticker is renamed.
Intrinio writes share classes with a dot (BRK.B); the app writes a hyphen (BRK-B); canonical_symbol compares them.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

SYMBOL_TABLES_EXCLUDED = ("ticker_aliases",)      # the alias table keeps the old symbol on purpose
# tables keyed by ticker_id with no unique key on it: the natural key that decides a collision when two rows merge
NATURAL_KEYS = {"events": ["event_type", "event_date"], "historical_reactions": ["event_type", "event_date"]}


def canonical_symbol(symbol: str | None) -> str:
    """The app's spelling of a ticker: upper case, a hyphen where Intrinio writes a dot (BRK.B -> BRK-B)."""
    return (symbol or "").upper().replace(".", "-")


async def unique_keys(session, table: str, column: str) -> list[list[str]]:
    """The other columns of every unique index on `table` that includes `column` (partial indexes included)."""
    rows = (await session.execute(text("""
        SELECT array_agg(a.attname ORDER BY k.ord) FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) ON true
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
        WHERE i.indisunique AND c.relname = :t AND c.relnamespace = 'public'::regnamespace
        GROUP BY i.indexrelid"""), {"t": table})).scalars().all()
    keys = [[c for c in cols if c != column] for cols in rows if column in cols]
    if not keys and table in NATURAL_KEYS:
        keys = [NATURAL_KEYS[table]]
    return keys


async def _merge_rows(session, table: str, column: str, keep, drop) -> dict[str, int]:
    """Move `drop`'s rows in `table` to `keep`; where `keep` already holds the same unique key, `drop`'s row goes."""
    out: dict[str, int] = {}
    for others in await unique_keys(session, table, column):
        if not others:
            if table == "tickers":
                continue                                  # the duplicate ticker row goes last, after its children moved
            res = await session.execute(text(f'DELETE FROM "{table}" WHERE "{column}" = :d'), {"d": drop})
        else:
            same = " AND ".join(f'k."{c}" IS NOT DISTINCT FROM d."{c}"' for c in others)
            if table == "events":                         # reactions that point at a duplicate event follow it to the kept one
                await session.execute(text(f"""
                    UPDATE historical_reactions hr SET event_id = k.id FROM events d JOIN events k ON k."{column}" = :k AND {same}
                    WHERE d."{column}" = :d AND hr.event_id = d.id"""), {"k": keep, "d": drop})
            res = await session.execute(text(f"""
                DELETE FROM "{table}" d WHERE d."{column}" = :d
                AND EXISTS (SELECT 1 FROM "{table}" k WHERE k."{column}" = :k AND {same})"""), {"k": keep, "d": drop})
        if res.rowcount:
            out[f"{table} dropped"] = out.get(f"{table} dropped", 0) + res.rowcount
    if table != "tickers":
        res = await session.execute(text(f'UPDATE "{table}" SET "{column}" = :k WHERE "{column}" = :d'), {"k": keep, "d": drop})
        if res.rowcount:
            out[f"{table} moved"] = res.rowcount
    return out


async def absorb_duplicate(session, keep: str, drop: str) -> dict[str, int]:
    """Fold the ticker row `drop` (a younger duplicate of the same security) into `keep`: every symbol-keyed and
    ticker_id-keyed row moves to `keep` unless `keep` already has it, system_metadata keys naming `drop` go where
    `keep` has the same key and are renamed otherwise, and `drop`'s ticker row is deleted. `keep` keeps its id."""
    ids = dict((await session.execute(text("SELECT symbol, id FROM tickers WHERE symbol IN (:k, :d)"), {"k": keep, "d": drop})).all())
    if keep not in ids or drop not in ids:
        raise ValueError(f"absorb needs both {keep} and {drop} as tickers")
    changed: dict[str, int] = {}
    ticker_id_tables = (await session.execute(text("""
        SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'ticker_id' ORDER BY table_name"""))).scalars().all()
    # reactions before events: a duplicate event's reactions are judged on their own key first, then repointed
    ordered = sorted(ticker_id_tables, key=lambda t: (t != "historical_reactions", t))
    for table in ordered:
        changed.update(await _merge_rows(session, table, "ticker_id", ids[keep], ids[drop]))
    for table in await symbol_tables(session):
        changed.update(await _merge_rows(session, table, "symbol", keep, drop))
    changed.update(await _move_metadata_keys(session, drop, keep))
    await session.execute(text("DELETE FROM tickers WHERE symbol = :d"), {"d": drop})
    changed["tickers dropped"] = 1
    return changed


async def _move_metadata_keys(session, old: str, new: str) -> dict[str, int]:
    """Rename system_metadata keys that name `old` as a segment; a key whose renamed form already exists is dropped."""
    out: dict[str, int] = {}
    res = await session.execute(text("""
        DELETE FROM system_metadata m WHERE m.key ~ ('(^|:)' || :o || '(:|$)') AND m.key <> :o
        AND EXISTS (SELECT 1 FROM system_metadata k WHERE k.key = regexp_replace(m.key, '(^|:)' || :o || '(:|$)', '\\1' || :n || '\\2', 'g'))"""),
        {"o": old, "n": new})
    if res.rowcount:
        out["system_metadata keys dropped (target exists)"] = res.rowcount
    res = await session.execute(text("""
        UPDATE system_metadata SET key = regexp_replace(key, '(^|:)' || :o || '(:|$)', '\\1' || :n || '\\2', 'g')
        WHERE key ~ ('(^|:)' || :o || '(:|$)') AND key <> :o"""), {"o": old, "n": new})
    if res.rowcount:
        out["system_metadata keys"] = res.rowcount
    return out


async def symbol_tables(session) -> list[str]:
    rows = (await session.execute(text("""
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'symbol' ORDER BY table_name"""))).scalars().all()
    return [t for t in rows if t not in SYMBOL_TABLES_EXCLUDED]


async def rename_symbol(session, old: str, new: str, renamed_on: date, reason: str, name: str | None = None) -> dict[str, int]:
    """Rename `old` (as stored) to `new` (canonical) everywhere. Returns {table_or_keys: rows changed}. If `new`
    already exists as a ticker for the same Intrinio security, that duplicate is absorbed into `old` first; for a
    different security it raises. The ticker's name becomes `name`, else its current record's name."""
    old, new = old.upper(), canonical_symbol(new)
    if old == new:
        raise ValueError("old and new symbol are the same")
    exists = (await session.execute(text("SELECT 1 FROM tickers WHERE symbol = :o"), {"o": old})).scalar()
    if not exists:
        raise ValueError(f"{old} is not a ticker")
    changed: dict[str, int] = {}
    taken = (await session.execute(text("SELECT 1 FROM tickers WHERE symbol = :n"), {"n": new})).scalar()
    if taken:
        recs = dict((await session.execute(text("""
            SELECT symbol, intrinio_security_id FROM security_records WHERE role = 'current' AND symbol IN (:o, :n)"""), {"o": old, "n": new})).all())
        if not recs.get(old) or recs.get(old) != recs.get(new):
            raise ValueError(f"{new} already exists as a ticker for another security; a rename onto a live symbol is not a rename")
        changed.update(await absorb_duplicate(session, old, new))
    for table in await symbol_tables(session):
        res = await session.execute(text(f'UPDATE "{table}" SET symbol = :n WHERE symbol = :o'), {"n": new, "o": old})
        if res.rowcount:
            changed[table] = res.rowcount
    changed.update(await _move_metadata_keys(session, old, new))
    await session.execute(text("""INSERT INTO ticker_aliases (old_symbol, symbol, renamed_on, reason) VALUES (:o, :n, :d, :r)
                                  ON CONFLICT (old_symbol) DO UPDATE SET symbol = :n, renamed_on = :d, reason = :r"""),
                          {"o": old, "n": new, "d": renamed_on, "r": reason})
    await session.execute(text("UPDATE ticker_aliases SET symbol = :n WHERE symbol = :o"), {"o": old, "n": new})   # older aliases follow
    await session.execute(text("DELETE FROM ticker_aliases WHERE old_symbol = symbol"))                             # a rename back leaves no self-alias
    changed["ticker_aliases"] = 1
    res = await session.execute(text("""
        UPDATE tickers t SET name = COALESCE(CAST(:name AS text), r.name) FROM security_records r
        WHERE r.symbol = t.symbol AND r.role = 'current' AND t.symbol = :n AND COALESCE(CAST(:name AS text), r.name) IS NOT NULL
        AND t.name IS DISTINCT FROM COALESCE(CAST(:name AS text), r.name)"""), {"name": name, "n": new})
    if res.rowcount:
        changed["tickers name"] = res.rowcount
    return changed


def detect_rename(symbol: str, stored_record_id: str | None, body: dict, existing_symbols: set[str],
                  record_ids: dict[str, str | None] | None = None) -> str | None:
    """The new symbol when Intrinio returns the record we already hold under another ticker; None otherwise.
    A rename needs the same record id (the same security) and a new ticker nobody else uses, unless the ticker that
    uses it holds the same record (a duplicate row the rename absorbs). BRK.B is BRK-B, not a rename."""
    new = canonical_symbol(body.get("ticker"))
    if not new or new == canonical_symbol(symbol) or not stored_record_id or body.get("id") != stored_record_id:
        return None
    if new in existing_symbols and (record_ids or {}).get(new) != stored_record_id:
        return None
    return new
