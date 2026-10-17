"""Frozen v2 backend regressions; Journal/SQLite fixtures only, no driver/network.

Fixed before implementation: only accepted bindings lower queue priority;
terminal non-UNKNOWN receipts project NOT_APPLIED plus receipt evidence; that
state, the receipt and application_cursor notification share one transaction.
Cached/UNKNOWN fencing, rollback/retry, omission, restart and isolation remain.
UNKNOWN ranking is observed read-only: an unresolved run never grants admission.
"""
from __future__ import annotations

import json

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError, LeaseLost
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.journal import DispatchBlocked
from sisyfus.workers.lead_journal import LeadJournal
from sisyfus.workers.mission_inbox import MissionInbox
from sisyfus.workers.protocol import Receipt, digest


BASE = 'Frozen controller prompt.\n{}'


def open_inbox(path):
    journal = LeadJournal(AutonomyStore(path))
    journal.bind({'parallelism': 2, 'max_calls': None, 'objective': 'fixed fixture',
                  'acceptance_hash': 'frozen', 'checks': {'frozen': {'sha': 'unchanged'}}})
    inbox = MissionInbox(journal)
    journal.after_event = inbox.observe_native_in
    return inbox


@pytest.fixture
def inbox(tmp_path):
    return open_inbox(tmp_path / 'autonomy.sqlite3')


def post(inbox, serial, text=None):
    return inbox.submit(text or ('fact-' + str(serial)), 'request_%04d' % serial,
        snapshot={'phase': 'IMPLEMENTING', 'nodes': [], 'all_verified': False}, controller={'running': True})


def reserve(inbox, key, role='worker', task_id='build'):
    inbox.journal.reserve(key, 'planner' if role == 'lead' else task_id, digest(BASE),
        on_reserved=lambda db: inbox.bind(db, key, role=role, task_id=task_id, prompt=BASE))
    return inbox.for_run(key)


def accept(inbox, key):
    inbox.journal.event(key, 'turn_bound', {'turn_id': 'accepted-' + key})


def close(inbox, key, status='ERROR'):
    return inbox.journal.complete(key, Receipt(status, error='fixture terminal without compliance claim').as_dict())


def drain_bound(inbox, cursor):
    application_cursor = 0
    while True:
        page = inbox.messages(cursor=cursor, application_cursor=application_cursor)
        application_cursor = page['application_cursor']
        if not page['has_more_updates']:
            return application_cursor


def application(message, key):
    return next(item for item in message['applications'] if item['run_key'] == key)


def test_error_without_acceptance_still_outranks_delivered_overflow(inbox):
    undelivered = [post(inbox, i, str(i) + 'u' * 19000) for i in range(1, 4)]
    assert reserve(inbox, 'never-accepted')['message_ids'] == [m['id'] for m in undelivered]
    close(inbox, 'never-accepted')
    delivered = [post(inbox, i, str(i) + 'd' * 19000) for i in range(4, 7)]
    assert reserve(inbox, 'accepted')['message_ids'] == [m['id'] for m in delivered]
    accept(inbox, 'accepted')
    close(inbox, 'accepted', 'COMPLETED')
    newest = post(inbox, 7, 'newest' + 'n' * 19000)
    next_binding = reserve(inbox, 'next-eligible')
    assert next_binding['message_ids'] == [undelivered[1]['id'], undelivered[2]['id'], newest['id']]
    assert set(next_binding['omitted_message_ids']) == {undelivered[0]['id'], *(m['id'] for m in delivered)}
    assert inbox.journal.store.verify_event_chain()['valid']


def test_unknown_without_acceptance_has_no_applied_priority_and_keeps_fence(inbox):
    undelivered = [post(inbox, i, str(i) + 'u' * 19000) for i in range(1, 4)]
    delivered = [post(inbox, i, str(i) + 'd' * 19000) for i in range(4, 7)]
    assert reserve(inbox, 'accepted')['message_ids'] == [m['id'] for m in delivered]
    accept(inbox, 'accepted')
    close(inbox, 'accepted', 'COMPLETED')
    assert reserve(inbox, 'unknown')['message_ids'] == [m['id'] for m in undelivered]
    frozen = inbox.for_run('unknown')
    receipt = close(inbox, 'unknown', 'UNKNOWN')
    newest = post(inbox, 7, 'newest' + 'n' * 19000)
    # This private selector is the same query bind uses; no fictitious admission
    # or clearing of UNKNOWN is needed to test its priority inputs.
    with inbox.journal.store._transaction(immediate=False) as db:
        applied = inbox._applied_message_ids(db, role='worker', task_id='build')
        assert applied == {m['id'] for m in delivered}
        assert inbox._applied_message_ids(db, role='worker', task_id='other') == set()
        assert inbox._applied_message_ids(db, role='lead', task_id=None) == set()
    ranked = sorted([*undelivered, *delivered, newest], key=lambda m: (m['id'] in applied, -m['seq']))
    assert [m['id'] for m in ranked[:3]] == [newest['id'], undelivered[2]['id'], undelivered[1]['id']]
    with pytest.raises(DispatchBlocked):
        reserve(inbox, 'blocked-next')
    assert inbox.journal.reserve('unknown', 'build', digest(BASE)) == receipt
    assert inbox.for_run('unknown') == frozen and inbox.for_run('blocked-next') is None
    with pytest.raises(LeaseLost):
        accept(inbox, 'unknown')


@pytest.mark.parametrize('status', ['ERROR', 'COMPLETED'])
def test_known_terminal_receipt_is_not_applied_and_incrementally_refreshes(inbox, status):
    entry = post(inbox, 1)
    reserve(inbox, 'terminal')
    application_cursor = drain_bound(inbox, entry['seq'])
    assert application(inbox.messages()['messages'][0], 'terminal')['status'] == 'BOUND'
    receipt = close(inbox, 'terminal', status)
    page = inbox.messages(cursor=entry['seq'], application_cursor=application_cursor)
    assert page['messages'] == [] and page['cursor'] == entry['seq']
    assert len(page['updates']) == 1 and page['application_cursor'] > application_cursor
    updated = page['updates'][0]
    outcome = application(updated, 'terminal')
    assert updated['status'] == 'RECEIVED' and outcome['status'] == 'NOT_APPLIED'
    assert outcome['delivery'] is None and outcome['receipt_status'] == status
    assert outcome['receipt_evidence']['recorded_prompt_acceptance'] is False
    assert outcome['receipt_evidence']['receipt_hash'] == digest(receipt)
    assert 'not' in outcome['receipt_evidence']['semantics'] and 'compliance' in outcome['receipt_evidence']['semantics']
    again = open_inbox(inbox.journal.store.path)
    assert again.messages(cursor=entry['seq'], application_cursor=application_cursor) == page
    assert not again.messages(cursor=entry['seq'], application_cursor=page['application_cursor'])['updates']
    assert again.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('status', ['ERROR', 'UNKNOWN', 'COMPLETED'])
def test_accepted_prompt_remains_applied_when_terminal_receipt_arrives(inbox, status):
    entry = post(inbox, 1)
    reserve(inbox, 'accepted')
    accept(inbox, 'accepted')
    application_cursor = drain_bound(inbox, entry['seq'])
    close(inbox, 'accepted', status)
    page = inbox.messages(cursor=entry['seq'], application_cursor=application_cursor)
    assert len(page['updates']) == 1
    outcome = application(page['updates'][0], 'accepted')
    assert outcome['status'] == 'APPLIED' and outcome['receipt_status'] == status
    assert outcome['receipt_evidence']['recorded_prompt_acceptance'] is True
    assert outcome['delivery']['turn_id'] == 'accepted-accepted'


def test_unknown_receipt_remains_bound_and_notifies_evidence_without_redispatch(inbox):
    entry = post(inbox, 1)
    reserve(inbox, 'unknown')
    application_cursor = drain_bound(inbox, entry['seq'])
    frozen = inbox.for_run('unknown')
    receipt = close(inbox, 'unknown', 'UNKNOWN')
    page = inbox.messages(cursor=entry['seq'], application_cursor=application_cursor)
    assert len(page['updates']) == 1
    outcome = application(page['updates'][0], 'unknown')
    assert outcome['status'] == 'BOUND' and outcome['receipt_status'] == 'UNKNOWN'
    assert outcome['receipt_evidence']['recorded_prompt_acceptance'] is False
    assert close(inbox, 'unknown', 'UNKNOWN') == receipt
    assert not inbox.messages(cursor=entry['seq'], application_cursor=page['application_cursor'])['updates']
    with pytest.raises(DispatchBlocked):
        reserve(inbox, 'new-key')
    assert inbox.for_run('unknown') == frozen


def test_receipt_notification_rolls_back_with_receipt_and_hash_chain(inbox):
    entry = post(inbox, 1)
    reserve(inbox, 'rollback')
    application_cursor = drain_bound(inbox, entry['seq'])
    before = inbox.journal.store.verify_event_chain()
    hook = inbox.journal.after_event
    def broken(db, key, kind, data):
        hook(db, key, kind, data)
        if kind == 'receipt':
            # Crash precisely after context notification, before canonical commit.
            assert db.execute('SELECT receipt_json FROM native_worker_runs WHERE key=?', (key,)).fetchone()[0]
            assert db.execute('SELECT count(*) FROM lead_mission_message_updates WHERE seq>?', (application_cursor,)).fetchone()[0] == 1
            raise ValueError('fixture crash after terminal context notification')
    inbox.journal.after_event = broken
    with pytest.raises(ValueError, match='fixture crash'):
        close(inbox, 'rollback')
    assert inbox.journal.runs()[0]['status'] == 'IN_FLIGHT' and inbox.journal.runs()[0]['receipt'] is None
    assert inbox.journal.store.verify_event_chain() == before
    assert not inbox.messages(cursor=entry['seq'], application_cursor=application_cursor)['updates']
    assert application(inbox.messages()['messages'][0], 'rollback')['status'] == 'BOUND'
    inbox.journal.after_event = hook
    close(inbox, 'rollback')
    page = inbox.messages(cursor=entry['seq'], application_cursor=application_cursor)
    assert len(page['updates']) == 1 and application(page['updates'][0], 'rollback')['status'] == 'NOT_APPLIED'
    assert inbox.journal.store.verify_event_chain()['valid']


def test_terminal_notification_is_once_on_cached_conflicting_and_hook_replay(inbox):
    entry = post(inbox, 1)
    reserve(inbox, 'cached')
    application_cursor = drain_bound(inbox, entry['seq'])
    receipt = close(inbox, 'cached')
    page = inbox.messages(cursor=entry['seq'], application_cursor=application_cursor)
    assert len(page['updates']) == 1
    before = inbox.journal.store.verify_event_chain()
    assert close(inbox, 'cached') == receipt
    assert inbox.journal.reserve('cached', 'build', digest(BASE), on_reserved=lambda _: pytest.fail('cached calls never bind')) == receipt
    with pytest.raises(IdempotencyConflictError):
        close(inbox, 'cached', 'COMPLETED')
    # Compatibility entry point must not produce duplicate terminal notices.
    inbox.observe_native('cached', 'receipt', receipt)
    assert inbox.journal.store.verify_event_chain() == before
    assert not inbox.messages(cursor=entry['seq'], application_cursor=page['application_cursor'])['updates']


def test_terminal_stream_pages_every_impacted_message_once(inbox):
    entries = [post(inbox, i) for i in range(1, 206)]
    binding = reserve(inbox, 'many')
    assert len(binding['message_ids']) == len(entries)
    cursor = entries[-1]['seq']
    application_cursor = drain_bound(inbox, cursor)
    initial_application_cursor = application_cursor
    close(inbox, 'many')
    seen = []
    while True:
        page = inbox.messages(cursor=cursor, application_cursor=application_cursor, limit=97)
        assert page['messages'] == [] and len(page['updates']) <= 97
        seen.extend(row['id'] for row in page['updates'])
        assert all(application(row, 'many')['status'] == 'NOT_APPLIED' for row in page['updates'])
        application_cursor = page['application_cursor']
        if not page['has_more_updates']:
            break
    assert seen == [m['id'] for m in entries]
    assert application_cursor - initial_application_cursor == len(entries)


def test_terminal_notification_does_not_mark_omitted_context(inbox):
    entries = [post(inbox, i, str(i) + 'x' * 19000) for i in range(1, 8)]
    binding = reserve(inbox, 'partial')
    cursor = entries[-1]['seq']
    application_cursor = drain_bound(inbox, cursor)
    close(inbox, 'partial')
    page = inbox.messages(cursor=cursor, application_cursor=application_cursor)
    assert {m['id'] for m in page['updates']} == set(binding['message_ids'])
    for m in inbox.messages()['messages']:
        if m['id'] in binding['omitted_message_ids']:
            assert not m['applications'] and m['status'] == 'RECEIVED'


def test_terminal_receipt_for_legacy_run_never_backfills_context(inbox):
    entry = post(inbox, 1)
    inbox.journal.reserve('legacy', 'build', digest(BASE))
    before = inbox.messages(cursor=entry['seq'])['application_cursor']
    close(inbox, 'legacy')
    assert inbox.for_run('legacy') is None
    assert not inbox.messages(cursor=entry['seq'], application_cursor=before)['updates']
    assert not inbox.messages()['messages'][0]['applications']


def test_stop_terminal_projection_and_updates_are_mission_isolated(inbox, tmp_path):
    other = open_inbox(tmp_path / 'other.sqlite3')
    a, b = post(inbox, 1), post(other, 1)
    assert a['id'] == b['id']
    reserve(inbox, 'run')
    reserve(other, 'run')
    ac, bc = drain_bound(inbox, a['seq']), drain_bound(other, b['seq'])
    inbox.journal.request_stop()
    close(inbox, 'run')
    page = inbox.messages(cursor=a['seq'], application_cursor=ac)
    assert application(page['updates'][0], 'run')['status'] == 'NOT_APPLIED'
    assert inbox.journal.state()['stopped']
    assert not other.messages(cursor=b['seq'], application_cursor=bc)['updates']
    assert application(other.messages()['messages'][0], 'run')['status'] == 'BOUND'
    assert other.journal.runs()[0]['status'] == 'IN_FLIGHT'


@pytest.mark.parametrize('status', ['ERROR', 'UNKNOWN', 'COMPLETED', 'NOT_STARTED'])
def test_reader_report_store_only_transaction_facade_completes_receipt(inbox, status):
    """Added/frozen before the optional-hook facade repair; no report driver."""
    from sisyfus.research_v2.reporting import ReportCoordinator

    coordinator = object.__new__(ReportCoordinator)
    coordinator.store = inbox.journal.store
    receipt = Receipt(status, error='fixture facade receipt').as_dict()
    with coordinator.store._transaction() as db:
        facade = coordinator._journal_in(db)
        assert set(vars(facade)) == {'store'}  # Actual legacy transaction facade.
        assert facade.reserve('reader-facade', 'reporter', digest(BASE)) is None
        assert facade.complete('reader-facade', receipt) == receipt
        assert json.loads(db.execute('SELECT receipt_json FROM native_worker_runs WHERE key=?',
                                     ('reader-facade',)).fetchone()[0]) == receipt
        assert facade.complete('reader-facade', receipt) == receipt
        with pytest.raises(IdempotencyConflictError):
            facade.complete('reader-facade', {**receipt, 'error': 'conflicting fixture receipt'})
    run = next(r for r in inbox.journal.runs() if r['key'] == 'reader-facade')
    assert run['receipt'] == receipt
    assert run['status'] == ('UNKNOWN' if status == 'UNKNOWN' else 'RECEIPTED')
    assert inbox.for_run('reader-facade') is None
    assert inbox.messages()['application_cursor'] == 0
    assert coordinator.store.verify_event_chain()['valid']


def test_reader_report_store_only_transaction_facade_records_events(inbox):
    from sisyfus.research_v2.reporting import ReportCoordinator

    coordinator = object.__new__(ReportCoordinator)
    coordinator.store = inbox.journal.store
    inbox.journal.reserve('reader-event', 'reporter', digest(BASE))
    with coordinator.store._transaction() as db:
        facade = coordinator._journal_in(db)
        assert set(vars(facade)) == {'store'}
        facade.event('reader-event', 'report_fixture', {'stage': 'author'})
    events = inbox.journal.events()
    assert sum(e['type'] == 'WORKER_REPORT_FIXTURE' for e in events) == 1
    assert coordinator.store.verify_event_chain()['valid']


def test_reader_report_facade_installed_hook_error_rolls_back(inbox):
    from sisyfus.research_v2.reporting import ReportCoordinator

    coordinator = object.__new__(ReportCoordinator)
    coordinator.store = inbox.journal.store
    entry = post(inbox, 1)
    reserve(inbox, 'facade-hook')
    application_cursor = drain_bound(inbox, entry['seq'])
    before = coordinator.store.verify_event_chain()
    observed = []

    def broken(db, key, kind, data):
        inbox.observe_native_in(db, key, kind, data)
        observed.append((key, kind))
        # Distinguish an absent optional attribute from a callback's own error.
        raise AttributeError('fixture installed callback error')

    with pytest.raises(AttributeError, match='fixture installed callback error'):
        with coordinator.store._transaction() as db:
            facade = coordinator._journal_in(db)
            facade.after_event = broken
            facade.complete('facade-hook', Receipt('ERROR').as_dict())
    assert observed == [('facade-hook', 'receipt')]
    run = next(r for r in inbox.journal.runs() if r['key'] == 'facade-hook')
    assert run['status'] == 'IN_FLIGHT' and run['receipt'] is None
    assert not inbox.messages(cursor=entry['seq'], application_cursor=application_cursor)['updates']
    assert coordinator.store.verify_event_chain() == before
