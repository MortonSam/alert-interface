"""A write that fails for any row fails the step. Every script that writes in a loop keeps a WriteFailures for its step: a database
error caught in a per-row handler is noted with the row's name, and finish() prints the rows, records them in the step outcome
(write_failures) and returns 1, so the production sequence and the nightly treat the step as failed instead of counting a quiet
loss (seven agreed release figures failed to store on 2026-10-07 on a column too narrow for their label, and the step exited 0).
Fetch failures keep each script's own rule; a database error raised outside any handler already ends the script non-zero.
"""
from __future__ import annotations

import sqlalchemy.exc

from app.services.redact import redact


def is_db_error(exc: BaseException) -> bool:
    """Pure: the exception came from the database layer (SQLAlchemy, asyncpg or psycopg2), not from a fetch or a parser."""
    mod = type(exc).__module__ or ""
    return isinstance(exc, sqlalchemy.exc.SQLAlchemyError) or mod.startswith("asyncpg") or mod.startswith("psycopg2")


class WriteFailures:
    def __init__(self, step_label: str) -> None:
        self.step = step_label
        self.rows: list[str] = []

    def note(self, row: str, exc: BaseException) -> bool:
        """Record `exc` against `row` when it is a database error; returns whether it was one."""
        if not is_db_error(exc):
            return False
        self.rows.append(f"{row}: {redact(exc)[:160]}")
        return True

    def add(self, row: str, exc: BaseException) -> None:
        """Record a failure at a known write site, whatever the exception type."""
        self.rows.append(f"{row}: {redact(exc)[:160]}")

    def exit_code(self, otherwise: int = 0) -> int:
        """Pure: 1 when any write failed (the rows are printed), else `otherwise`."""
        if self.rows:
            print(f"  {len(self.rows)} write(s) failed; the step fails: " + "; ".join(self.rows[:20]) + (" ..." if len(self.rows) > 20 else ""), flush=True)
            return 1
        return otherwise

    async def finish(self, otherwise: int = 0) -> int:
        """exit_code(), with the failed rows recorded in the step outcome when there are any."""
        code = self.exit_code(otherwise)
        if self.rows:
            from app.services.step_outcomes import record_step_fields
            await record_step_fields(self.step, {"write_failures": self.rows[:50]})
        return code
