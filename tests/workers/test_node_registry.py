"""Frozen stage2 identity fixtures; no native/remote-machine acceptance claim."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.lead_journal import LeadJournal
from sisyfus.workers.node_registry import NodeRegistry


@pytest.fixture
def registry(tmp_path):
    return NodeRegistry(LeadJournal(AutonomyStore(tmp_path / 'autonomy.sqlite3')))


def enroll(registry, ident='enroll_0001', name='测试节点'):
    return registry.enroll(ident, name, ['codex'], ['gpt-6.1-sol'])


def test_once_only_secret_hash_at_rest_and_restart(registry):
    first = enroll(registry)
    assert len(first['secret']) == 64
    assert registry.authenticate(first['node_id'], first['secret']) is True
    replay = enroll(registry)
    assert replay == first | {'secret': None}
    assert registry.inventory() == [{k: v for k, v in first.items() if k != 'secret'}]
    reopened = NodeRegistry(LeadJournal(AutonomyStore(registry.journal.store.path)))
    assert reopened.mission_id == registry.mission_id
    assert enroll(reopened) == replay
    assert reopened.authenticate(first['node_id'], first['secret']) is True
    with registry.journal.store._transaction(immediate=False) as db:
        dump = '\n'.join(db.iterdump())
        saved = db.execute('SELECT credential_digest FROM remote_nodes').fetchone()[0]
        assert first['secret'] not in dump
        assert saved == registry._credential(first['node_id'], first['secret'])
        assert saved in dump
    assert registry.journal.store.verify_event_chain()['valid']


def test_conflicting_enrollment_and_capabilities(registry):
    first = enroll(registry)
    with pytest.raises(IdempotencyConflictError):
        enroll(registry, name='另一个节点')
    assert registry.authenticate(first['node_id'], first['secret'])
    assert len(registry.inventory()) == 1


@pytest.mark.parametrize('drivers,models', [([], ['gpt-6.1-sol']), (['shell'], ['gpt-6.1-sol']),
    (['codex', 'claude-code'], ['gpt-6.1-sol']), (['codex'], ['auto']),
    (['codex'], ['claude-opus-5-5']), (['codex'], ['gpt-6.1-sol','auto']), (None, None)])
def test_v1_capability_boundary(registry, drivers, models):
    with pytest.raises(ValueError):
        registry.enroll('enroll_0001', 'node', drivers, models)
    assert registry.inventory() == []


@pytest.mark.parametrize('ident,name', [('short', 'node'), ('../enroll', 'node'),
    (None, 'node'), ('x'*101, 'node'), ('enroll_0001', ''), ('enroll_0001', ' '),
    ('enroll_0001', None), ('enroll_0001', '中'*100), ('enroll_0001', 'a\x00b')])
def test_invalid_inputs_do_not_write(registry, ident, name):
    before = registry.journal.events()
    with pytest.raises(ValueError):
        registry.enroll(ident, name, ['codex'], ['gpt-6.1-sol'])
    assert registry.inventory() == []
    assert registry.journal.events() == before


def test_wrong_secret_cross_node_revocation_and_replay(registry):
    a, b = enroll(registry), enroll(registry, 'enroll_0002', 'second')
    assert not registry.authenticate(a['node_id'], b['secret'])
    assert not registry.authenticate('unknown', a['secret'])
    assert not registry.authenticate(a['node_id'], None)
    assert not registry.authenticate(a['node_id'], 'not-a-secret')
    revoked = registry.revoke(a['node_id'])
    assert revoked['status'] == 'REVOKED' and revoked['revoked_at']
    head = registry.journal.events()
    assert registry.revoke(a['node_id']) == revoked
    assert registry.journal.events() == head
    assert not registry.authenticate(a['node_id'], a['secret'])
    assert registry.authenticate(b['node_id'], b['secret'])
    assert enroll(registry) == revoked | {'secret': None}
    with pytest.raises(ValueError, match='unknown'):
        registry.revoke('unknown')


def test_atomic_event_failure_and_retry(registry, monkeypatch):
    original = registry.journal.store._append_event
    def fail(*args, **kwargs):
        if kwargs['event_type'] == 'WORKER_NODE_ENROLLED':
            raise RuntimeError('injected chain write failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(registry.journal.store, '_append_event', fail)
    with pytest.raises(RuntimeError, match='injected'):
        enroll(registry)
    assert registry.inventory() == []
    monkeypatch.setattr(registry.journal.store, '_append_event', original)
    assert enroll(registry)['secret']
    assert registry.journal.store.verify_event_chain()['valid']


def test_concurrent_enrollment_returns_one_secret(registry):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: enroll(registry), range(8)))
    assert len({r['node_id'] for r in results}) == 1
    assert sum(r['secret'] is not None for r in results) == 1
    assert len(registry.inventory()) == 1
    assert registry.journal.store.verify_event_chain()['valid']


def test_mission_namespace_isolation_and_schema_fence(registry, tmp_path):
    first = enroll(registry)
    other = NodeRegistry(LeadJournal(AutonomyStore(tmp_path / 'other' / 'autonomy.sqlite3')))
    assert other.mission_id != registry.mission_id
    assert not other.authenticate(first['node_id'], first['secret'])
    assert other.inventory() == []
    with registry.journal.store._transaction() as db:
        db.execute("UPDATE metadata SET value='future' WHERE key='remote_node_schema'")
    with pytest.raises(ValueError, match='schema'):
        NodeRegistry(registry.journal)


def test_identity_events_are_in_canonical_chain(registry):
    first = enroll(registry)
    registry.revoke(first['node_id'])
    with registry.journal.store._transaction(immediate=False) as db:
        events = [json.loads(r[0]) for r in db.execute("SELECT data_json FROM events WHERE event_type LIKE 'WORKER_NODE_%'")]
        assert all(event['mission_id'] == registry.mission_id for event in events)
        assert db.execute("SELECT count(*) FROM evidence").fetchone()[0] == 0
    assert registry.journal.store.path.name == 'autonomy.sqlite3'
    assert registry.journal.store.verify_event_chain()['valid']
