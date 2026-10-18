"""Frozen regressions for independent-review v1's two backend P2 findings.

Scenarios fixed before the first run: ordinary/default-purpose compatibility,
all explicit non-ordinary purposes excluded from binding and session inheritance,
_lead_json improvement isolation, cached/UNKNOWN replay preservation, and invalid
worker base prompts retaining their native reservation plus durable ERROR receipt.
Only protocol stubs are used; this file makes no live native/model claims.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sisyfus.workers.journal import DispatchBlocked
from sisyfus.workers.mission_inbox import MAX_PROMPT_BYTES
from sisyfus.workers.protocol import Receipt, digest
from test_lead_mission import make_spec, mission


OPERATOR_DATA = 'pending operator supplement: do not promote this raw text into a procedure'
BASE_PROMPT = 'Read this controller fixture.\n{}'


def post(m, request_id='request_0001'):
    return m.inbox.submit(OPERATOR_DATA, request_id, snapshot=m.snapshot(), controller={'running': False})


@pytest.mark.parametrize('purpose', ['improvement', 'procedure_promotion', 'promotion', 'candidate_procedure', 'future-purpose'])
def test_explicit_nonordinary_lead_purposes_never_bind_or_inherit_context(tmp_path, purpose):
    m = mission(tmp_path, make_spec(tmp_path))
    cwd = Path(m.spec['source'])
    first = post(m)
    ordinary = m.role_call('lead', 'ordinary-before', BASE_PROMPT, cwd, metadata={'purpose': 'architecture'})
    assert m.inbox.for_run('ordinary-before')['message_ids'] == [first['id']]
    pending = post(m, 'request_0002')
    frozen_checks = digest(m.spec['checks'])
    promoted = m.role_call('lead', 'excluded', BASE_PROMPT, cwd, metadata={'purpose': purpose})
    request = m.drivers['claude'].requests[-1]
    assert request.prompt == BASE_PROMPT and OPERATOR_DATA not in request.prompt
    assert request.session_id is None
    assert m.inbox.for_run('excluded') is None
    assert 'context_binding_hash' not in promoted
    assert m.journal.get('roles', 'excluded')['purpose'] == purpose
    pending_row = next(row for row in m.inbox.messages()['messages'] if row['id'] == pending['id'])
    assert pending_row['status'] == 'RECEIVED' and pending_row['applications'] == []
    assert digest(m.spec['checks']) == frozen_checks and not m.snapshot()['all_verified']
    # Later ordinary calls resume only the ordinary history, not a procedure call.
    m.role_call('lead', 'ordinary-after', BASE_PROMPT, cwd, metadata={'purpose': 'diagnosis'})
    assert m.drivers['claude'].requests[-1].session_id == ordinary['session_id']
    assert m.drivers['claude'].requests[-1].session_id != promoted['session_id']
    assert pending['id'] in m.inbox.for_run('ordinary-after')['message_ids']
    # Default caller metadata cannot reclassify a pinned purpose on receipt replay.
    count = len(m.drivers['claude'].requests)
    assert m.role_call('lead', 'excluded', BASE_PROMPT, cwd) == promoted
    assert len(m.drivers['claude'].requests) == count and m.inbox.for_run('excluded') is None
    assert m.store.verify_event_chain()['valid']


@pytest.mark.parametrize('metadata', [None, {}, {'purpose': None}, {'purpose': 'architecture'}, {'purpose': 'diagnosis'}])
def test_ordinary_and_legacy_default_purpose_calls_still_receive_context(tmp_path, metadata):
    m = mission(tmp_path, make_spec(tmp_path))
    entry = post(m)
    m.role_call('lead', 'ordinary', BASE_PROMPT, Path(m.spec['source']), metadata=metadata)
    binding = m.inbox.for_run('ordinary')
    assert binding is not None and binding['message_ids'] == [entry['id']]
    request = m.drivers['claude'].requests[-1]
    assert json.loads(request.prompt.split('\n', 1)[1])['operator_context']['messages'][0]['text'] == OPERATOR_DATA
    assert entry['id'] in binding['message_hashes']
    assert m.inbox.messages()['messages'][0]['applications'][0]['status'] == 'NOT_APPLIED'


def test_lead_json_improvement_keeps_pending_context_out_of_procedure_input(tmp_path):
    procedure = 'Plan the smallest graph using only canonical evidence and frozen checks.'
    def claude(request, emit, _controls):
        if request.prompt.startswith('Improve'):
            emit('native_event', {'type': 'assistant', 'message': {'model': request.model}})
            return Receipt('COMPLETED', session_id='isolated-procedure-session', output=json.dumps({
                'procedure': procedure, 'rationale': 'use canonical evidence only', 'evidence': ['fixture-evidence']}))
    m = mission(tmp_path, make_spec(tmp_path), claude=claude)
    cwd = Path(m.spec['source'])
    post(m)
    m.role_call('lead', 'architecture-before', BASE_PROMPT, cwd, metadata={'purpose': 'architecture'})
    pending = post(m, 'request_0002')
    def validate(raw):
        assert raw['procedure'] == procedure
    raw, key = m._lead_json('improvement', 'fixed-review-seed', 'Improve controller procedure.\n{}', validate)
    assert raw['procedure'] == procedure and OPERATOR_DATA not in json.dumps(raw)
    assert m.inbox.for_run(key) is None
    request = m.drivers['claude'].requests[-1]
    assert 'operator_context' not in json.loads(request.prompt.split('\n', 1)[1])
    assert OPERATOR_DATA not in request.prompt and request.session_id is None
    record = next(row for row in m.inbox.messages()['messages'] if row['id'] == pending['id'])
    assert record['status'] == 'RECEIVED' and record['applications'] == []
    assert m.store.verify_event_chain()['valid']


def test_unknown_improvement_restart_never_rebinds_or_resends(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path), claude=lambda *_: Receipt('UNKNOWN', error='fixture unknown procedure call'))
    cwd = Path(m.spec['source'])
    post(m)
    with pytest.raises(DispatchBlocked, match='UNKNOWN'):
        m.role_call('lead', 'unknown-procedure', BASE_PROMPT, cwd, metadata={'purpose': 'improvement'})
    assert m.inbox.for_run('unknown-procedure') is None
    again = mission(tmp_path, None)
    post(again, 'request_0002')
    with pytest.raises(DispatchBlocked, match='UNKNOWN'):
        again.role_call('lead', 'unknown-procedure', BASE_PROMPT, Path(again.spec['source']))
    assert not again.drivers['claude'].requests
    assert again.inbox.for_run('unknown-procedure') is None
    assert len(again.journal.runs()) == 1
    assert all(row['applications'] == [] for row in again.inbox.messages()['messages'])


@pytest.mark.parametrize('bad_prompt,error_fragment', [
    ('x' * (MAX_PROMPT_BYTES + 1), 'prompt exceeds 200KB'),
    ('界' * (MAX_PROMPT_BYTES // 3 + 1), 'prompt exceeds 200KB'),
    ('', 'task_id, explicit model, and prompt are required'),
    (' \n\t', 'task_id, explicit model, and prompt are required'),
])
@pytest.mark.parametrize('with_pending_context', [False, True])
def test_invalid_worker_prompt_retains_reservation_error_receipt_and_restart(tmp_path, bad_prompt, error_fragment, with_pending_context):
    m = mission(tmp_path, make_spec(tmp_path))
    m._initial_plan()
    if with_pending_context:
        post(m)
    frozen_spec = digest(m.spec)
    continuation = m.store.claim_due_continuation('review-worker-fixture')
    assert continuation is not None
    decision = m.planner(continuation, m.runtime.planner_context(continuation))
    assert decision.capability == 'workers.execute'
    arguments = {**decision.arguments, 'prompt': bad_prompt}
    key = 'review-invalid-worker'
    execute = m.registry.get('workers.execute').capability.execute
    result = execute(arguments, idempotency_key=key)
    assert result.status == 'ERROR'
    assert error_fragment in result.observation['error']
    runs = m.journal.runs()
    assert len(runs) == 1 and runs[0]['key'] == key and runs[0]['task_id'] == 'build'
    assert runs[0]['status'] == 'RECEIPTED' and runs[0]['receipt']['status'] == 'ERROR'
    assert error_fragment in runs[0]['receipt']['error']
    assert m.inbox.for_run(key) is None and 'context_binding_hash' not in runs[0]['receipt']
    assert not m.drivers['codex'].requests and digest(m.spec) == frozen_spec
    assert not m.snapshot()['all_verified'] and m.store.verify_event_chain()['valid']
    assert len([e for e in m.journal.events(0, 1000) if e['type'] == 'WORKER_RESERVED']) == 1
    assert not any(e['type'] == 'WORKER_MISSION_CONTEXT_BOUND' for e in m.journal.events(0, 1000))
    assert all(row['applications'] == [] for row in m.inbox.messages()['messages'])
    assert execute(arguments, idempotency_key=key).as_dict() == result.as_dict()
    again = mission(tmp_path, None)
    post(again, 'request_0002')
    replay = again.registry.get('workers.execute').capability.execute(arguments, idempotency_key=key)
    assert replay.as_dict() == result.as_dict()
    assert len(again.journal.runs()) == 1 and not again.drivers['codex'].requests
    assert again.inbox.for_run(key) is None
    assert all(row['applications'] == [] for row in again.inbox.messages()['messages'])
