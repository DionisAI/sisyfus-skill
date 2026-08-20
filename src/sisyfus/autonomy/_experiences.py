from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from ._common import _decode_json
from .models import canonical_json, stable_id


class ExperienceMixin:
    def _upsert_experience_locked(
        self,
        connection: sqlite3.Connection,
        *,
        evidence_id: str,
        pattern_key: str,
        polarity: str,
        claim: str,
        scope: Mapping[str, Any],
        confidence: float,
        outcome: str,
        now: str,
    ) -> None:
        if polarity not in {"positive", "negative", "operational"}:
            raise ValueError(f"unsupported experience polarity: {polarity}")
        if outcome not in {"support", "counterexample"}:
            raise ValueError(f"unsupported experience outcome: {outcome}")
        scope_hash = stable_id("scope", dict(scope), length=24)
        experience_id = stable_id("exp", pattern_key, scope_hash, polarity, length=24)
        row = connection.execute(
            "SELECT * FROM experiences WHERE pattern_key = ? AND scope_hash = ? AND polarity = ?",
            (pattern_key, scope_hash, polarity),
        ).fetchone()
        if row is None:
            supports = 1 if outcome == "support" else 0
            counterexamples = 1 if outcome == "counterexample" else 0
            connection.execute(
                """
                INSERT INTO experiences(
                    id, pattern_key, scope_hash, polarity, claim, scope_json,
                    confidence, status, supports, counterexamples, evidence_ids_json,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?)
                """,
                (
                    experience_id,
                    pattern_key,
                    scope_hash,
                    polarity,
                    claim,
                    canonical_json(dict(scope)),
                    max(0.0, min(1.0, float(confidence))),
                    supports,
                    counterexamples,
                    canonical_json([evidence_id]),
                    now,
                    now,
                ),
            )
            return
        evidence_ids = _decode_json(row["evidence_ids_json"], [])
        if evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
        supports = int(row["supports"]) + (1 if outcome == "support" else 0)
        counterexamples = int(row["counterexamples"]) + (1 if outcome == "counterexample" else 0)
        empirical = (supports + 1.0) / (supports + counterexamples + 2.0)
        updated_confidence = max(0.0, min(1.0, 0.5 * float(row["confidence"]) + 0.5 * empirical))
        status = "validated" if supports >= 2 and counterexamples == 0 else "contradicted" if counterexamples >= 2 else "candidate"
        connection.execute(
            """
            UPDATE experiences
            SET claim = ?, scope_json = ?, confidence = ?, status = ?, supports = ?,
                counterexamples = ?, evidence_ids_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                claim,
                canonical_json(dict(scope)),
                updated_confidence,
                status,
                supports,
                counterexamples,
                canonical_json(evidence_ids),
                now,
                row["id"],
            ),
        )

