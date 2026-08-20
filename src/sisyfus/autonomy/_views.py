from __future__ import annotations

from contextlib import closing
from typing import Any


class ViewMixin:
    def snapshot(self, continuation_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            continuation = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
            if continuation is None:
                raise KeyError(f"unknown continuation: {continuation_id}")
            opportunity = connection.execute(
                "SELECT * FROM opportunities WHERE id = ?", (continuation["opportunity_id"],)
            ).fetchone()
            events = connection.execute(
                "SELECT * FROM continuation_events WHERE continuation_id = ? ORDER BY seq ASC", (continuation_id,)
            ).fetchall()
            decisions = connection.execute(
                "SELECT * FROM decisions WHERE continuation_id = ? ORDER BY step_index ASC, created_at ASC",
                (continuation_id,),
            ).fetchall()
            evidence = connection.execute(
                "SELECT * FROM evidence WHERE continuation_id = ? ORDER BY created_at ASC", (continuation_id,)
            ).fetchall()
            experiences = connection.execute(
                "SELECT * FROM experiences WHERE status = 'validated' ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()
        return {
            "opportunity": self._row(opportunity),
            "continuation": self._row(continuation),
            "events": [self._row(row) for row in events],
            "decisions": [self._row(row) for row in decisions],
            "evidence": [self._row(row) for row in evidence],
            "experiences": [self._row(row) for row in experiences],
        }

    def list_experiences(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM experiences WHERE status = ? ORDER BY updated_at DESC", (status,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM experiences ORDER BY updated_at DESC").fetchall()
        return [self._row(row) or {} for row in rows]

