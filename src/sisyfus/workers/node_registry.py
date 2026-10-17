"""Controller-owned Remote Node v1 identities in Journal's canonical store.

NodeRegistry(journal) works with Journal or LeadJournal. enroll(request_id,
name, drivers, models) returns {mission_id, node_id, request_id, name, drivers,
models, status, created_at, revoked_at, secret}. Only the first successful
enrollment returns a secret; replay returns secret=None, even after revocation.
inventory() returns a list of the same public records WITHOUT secret.
authenticate(node_id, secret) returns bool; revoke(node_id) returns a public
record (idempotent). Unknown revocations raise ValueError, enrollment conflicts
raise IdempotencyConflictError. v1 capabilities are exactly ['codex'] and
['gpt-6.1-sol']. Enrollment/authentication do not dispatch or confer operator
permissions. The caller is responsible for authenticating controller actions.

Credentials have 256 bits of random entropy; only a node-bound SHA256 digest
is persisted, including events. The durable mission_id is a transport namespace
in the SAME autonomy.sqlite3, not a new task identity or acceptance record.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from typing import Any

from ..autonomy.models import canonical_json, utc_now
from ..autonomy.policy import IdempotencyConflictError
from .protocol import digest

_ID = re.compile(r"[A-Za-z0-9_-]{8,100}\Z")


def validate_request_id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('request_id must be 8..100 letters, digits, underscores or hyphens')
    return value


class NodeRegistry:
    def __init__(self, journal: Any):
        self.journal = journal
        with journal.store._transaction() as db:
            schema = db.execute("SELECT value FROM metadata WHERE key='remote_node_schema'").fetchone()
            if schema and schema[0] != '1':
                raise ValueError('incompatible remote node schema')
            db.execute('CREATE TABLE IF NOT EXISTS remote_nodes ('
                       'node_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, '
                       'fingerprint TEXT NOT NULL, credential_digest TEXT NOT NULL, '
                       'name TEXT NOT NULL, drivers_json TEXT NOT NULL, models_json TEXT NOT NULL, '
                       'status TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT)')
            db.execute("INSERT OR IGNORE INTO metadata VALUES('remote_node_schema','1')")
            row = db.execute("SELECT value FROM metadata WHERE key='remote_node_mission_id'").fetchone()
            if row is None:
                self.mission_id = 'mission_' + secrets.token_hex(16)
                db.execute("INSERT INTO metadata VALUES('remote_node_mission_id',?)", (self.mission_id,))
                journal._event(db, 'node_namespace', self.mission_id, {'mission_id': self.mission_id}, actor='controller')
            else:
                self.mission_id = row[0]

    def _public(self, row: Any) -> dict[str, Any]:
        return {'mission_id': self.mission_id, 'node_id': row['node_id'],
                'request_id': row['request_id'], 'name': row['name'],
                'drivers': json.loads(row['drivers_json']), 'models': json.loads(row['models_json']),
                'status': row['status'], 'created_at': row['created_at'], 'revoked_at': row['revoked_at']}

    def _active(self, db: Any, node_id: str) -> Any:
        if not isinstance(node_id, str):
            raise ValueError('invalid node identity')
        row = db.execute('SELECT * FROM remote_nodes WHERE node_id=?', (node_id,)).fetchone()
        if row is None or row['status'] != 'ACTIVE':
            raise PermissionError('node is unknown or revoked')
        return row

    @staticmethod
    def _credential(node_id: str, secret: str) -> str:
        return hashlib.sha256((node_id + '\0' + secret).encode()).hexdigest()

    def enroll(self, request_id: str, name: str, drivers: list[str], models: list[str]) -> dict[str, Any]:
        ident = validate_request_id(request_id)
        if not isinstance(name, str) or not name.strip() or len(name.encode()) > 200 or any(ord(c) < 32 for c in name):
            raise ValueError('node name must be nonempty text up to 200 UTF-8 bytes')
        if drivers != ['codex'] or models != ['gpt-6.1-sol']:
            raise ValueError('v1 requires codex and explicit gpt-6.1-sol')
        fingerprint = digest({'name': name, 'drivers': drivers, 'models': models})
        with self.journal.store._transaction() as db:
            row = db.execute('SELECT * FROM remote_nodes WHERE request_id=?', (ident,)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint:
                    raise IdempotencyConflictError('conflicting node enrollment')
                return self._public(row) | {'secret': None}
            node_id = 'node_' + secrets.token_hex(16)
            secret = secrets.token_hex(32)
            credential = self._credential(node_id, secret)
            db.execute('INSERT INTO remote_nodes VALUES(?,?,?,?,?,?,?,\'ACTIVE\',?,NULL)',
                       (node_id, ident, fingerprint, credential, name, canonical_json(drivers), canonical_json(models), utc_now()))
            row = db.execute('SELECT * FROM remote_nodes WHERE node_id=?', (node_id,)).fetchone()
            public = self._public(row)
            self.journal._event(db, 'node_enrolled', node_id, public | {'credential_digest': credential}, actor='controller')
            return public | {'secret': secret}

    def inventory(self) -> list[dict[str, Any]]:
        with self.journal.store._transaction(immediate=False) as db:
            return [self._public(r) for r in db.execute('SELECT * FROM remote_nodes ORDER BY rowid').fetchall()]

    def authenticate(self, node_id: str, secret: str) -> bool:
        if not isinstance(node_id, str) or not isinstance(secret, str) or len(secret) != 64:
            return False
        with self.journal.store._transaction(immediate=False) as db:
            row = db.execute('SELECT * FROM remote_nodes WHERE node_id=?', (node_id,)).fetchone()
            return bool(row and row['status'] == 'ACTIVE' and hmac.compare_digest(
                row['credential_digest'], self._credential(node_id, secret)))

    def revoke(self, node_id: str) -> dict[str, Any]:
        if not isinstance(node_id, str):
            raise ValueError('invalid node identity')
        with self.journal.store._transaction() as db:
            row = db.execute('SELECT * FROM remote_nodes WHERE node_id=?', (node_id,)).fetchone()
            if row is None:
                raise ValueError('unknown node identity')
            if row['status'] != 'REVOKED':
                db.execute("UPDATE remote_nodes SET status='REVOKED',revoked_at=? WHERE node_id=?", (utc_now(), node_id))
                row = db.execute('SELECT * FROM remote_nodes WHERE node_id=?', (node_id,)).fetchone()
                self.journal._event(db, 'node_revoked', node_id, self._public(row), actor='controller')
            return self._public(row)
