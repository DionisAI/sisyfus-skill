"""TEST-ONLY late identity-resource errors through actual authenticated HTTP.

Two cases, frozen before outcomes. All source/auth/session delegates stay real;
only the exact database _inode inside the selected recheck raises a rare OS
fault. The original fourteen tests and production bytes remain independent.
"""
from __future__ import annotations

import errno
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys

import pytest

from sisyfus.workers import node_gateway as module
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.node_claims import NodeClaims
from test_node_gateway import call, env, forbidden_native, gateway_type, state


# Original unmodified deletion guard, installed before any fixture or socket.
sys.addaudithook(runpy.run_path(str(Path(__file__).resolve().parents[2] /
                    'scripts/test_retained.py'), run_name='late_auth_retained_guard')['guard_deletion'])

ABSENT_MESSAGE = 'selected mission has no bound control database'
OS_MESSAGE = 'selected control resource is unavailable'
MESSAGE_MARKER = 'LATE_AUTH_OS_MESSAGE_MUST_STAY_PRIVATE'
FILENAME_MARKER = 'LATE_AUTH_OS_FILENAME_MUST_STAY_PRIVATE'
FILENAME2_MARKER = 'LATE_AUTH_OS_FILENAME2_MUST_STAY_PRIVATE'
FOREIGN_SECRET = '6' * 64
BODY = {'request_id': 'late_auth_path_diagnostic_0001'}


@pytest.fixture(autouse=True)
def retained_loopback_no_native(tmp_path_factory, monkeypatch):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'explicit isolated loopback opt-in required'
    assert type(tmp_path_factory).__name__ == 'RetainedPaths', 'use the unchanged retained runner'
    attempts = {'subprocess': 0}

    def launch(*args, **kwargs):
        attempts['subprocess'] += 1
        return forbidden_native(*args, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', launch)
    return attempts


def physical(e):
    content, auxiliary = {}, []
    for path in e.hub.directory.rglob('*'):
        name = str(path.relative_to(e.hub.directory))
        if path.name.endswith(('-wal', '-shm')):
            auxiliary.append(name)
        elif path.is_file():
            content[name] = {'bytes': path.stat().st_size,
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        elif path.is_dir():
            content[name] = {'kind': 'directory'}
    return content, sorted(auxiliary)


def trace_exact_recheck(e, monkeypatch, *, stage, fault, expected_type):
    seen = {'auth_calls': 0, 'auth_returns': 0, 'credential_compare': 0,
            'credential_results': [], 'registered_credential_arguments': [],
            'directory_inode': 0, 'database_inode': 0, 'approved_spec': 0,
            'rechecks': 0, 'faults': 0, 'session_calls': 0, 'session_completed': 0,
            'real_session_identity': False, 'node_claims_property': 0,
            'registry_constructor': 0, 'claims_constructor': 0,
            'backend_dispatch': 0, 'native_or_controller_dispatch': 0,
            'escaped_recheck_type': None, 'escaped_recheck_exact_builtin': False,
            'trace': []}
    active = {'stage': None}
    real_auth, real_inode = module._auth, module._inode
    real_check, real_spec = module._check_identity, module.approved_spec
    real_compare = module._RegistryReader.authenticate
    real_session = e.hub._session

    @wraps(real_auth)
    def auth(*args, **kwargs):
        seen['auth_calls'] += 1
        seen['trace'].append('auth_enter')
        result = real_auth(*args, **kwargs)
        seen['auth_returns'] += 1
        seen['trace'].append('auth_return')
        return result

    @wraps(real_compare)
    def compare(reader, node_id, secret):
        result = real_compare(reader, node_id, secret)
        seen['credential_compare'] += 1
        seen['credential_results'].append(result)
        seen['registered_credential_arguments'].append(
            node_id == e.node['node_id'] and secret == e.node['secret'])
        seen['trace'].append('real_credential_compare')
        return result

    @wraps(real_check)
    def check(identity):
        seen['rechecks'] += 1
        current = 'handler-admission' if seen['session_completed'] else 'auth-exit'
        seen['trace'].append('recheck_enter:' + current)
        previous, active['stage'] = active['stage'], current
        try:
            return real_check(identity)
        except Exception as exc:
            seen['escaped_recheck_type'] = type(exc).__name__
            seen['escaped_recheck_exact_builtin'] = type(exc) is expected_type
            raise
        finally:
            active['stage'] = previous

    @wraps(real_inode)
    def inode(path, *, directory=False):
        if path == e.mission.directory and directory:
            seen['directory_inode'] += 1
        elif path == e.mission.directory / 'autonomy.sqlite3' and not directory:
            seen['database_inode'] += 1
            if (active['stage'] == stage and seen['credential_results']
                    and all(result is True for result in seen['credential_results'])):
                seen['faults'] += 1
                seen['trace'].append('database_inode_fault:' + stage)
                raise fault
        return real_inode(path, directory=directory)

    @wraps(real_spec)
    def spec(*args, **kwargs):
        seen['approved_spec'] += 1
        return real_spec(*args, **kwargs)

    @wraps(real_session)
    def session(*args, **kwargs):
        seen['session_calls'] += 1
        seen['trace'].append('real_session_enter')
        if stage == 'auth-exit':
            return forbidden_native(*args, **kwargs)
        result = real_session(*args, **kwargs)
        seen['session_completed'] += 1
        seen['real_session_identity'] = (result is e.hub._sessions[e.ident]
                                         and result.mission is e.mission)
        seen['trace'].append('real_session_return')
        return result

    def claims_property(_mission):
        seen['node_claims_property'] += 1
        return forbidden_native()

    def registry(*args, **kwargs):
        seen['registry_constructor'] += 1
        return forbidden_native(*args, **kwargs)

    def claims(*args, **kwargs):
        seen['claims_constructor'] += 1
        return forbidden_native(*args, **kwargs)

    @wraps(NodeClaims.claim)
    def dispatch(*args, **kwargs):
        seen['backend_dispatch'] += 1
        return forbidden_native(*args, **kwargs)

    def native(*args, **kwargs):
        seen['native_or_controller_dispatch'] += 1
        return forbidden_native(*args, **kwargs)

    monkeypatch.setattr(module, '_auth', auth)
    monkeypatch.setattr(module, '_check_identity', check)
    monkeypatch.setattr(module, '_inode', inode)
    monkeypatch.setattr(module, 'approved_spec', spec)
    monkeypatch.setattr(module._RegistryReader, 'authenticate', compare)
    monkeypatch.setattr(e.hub, '_session', session)
    monkeypatch.setattr(LeadMission, 'node_claims', property(claims_property))
    monkeypatch.setattr(module.NodeRegistry, '__init__', registry)
    monkeypatch.setattr(NodeClaims, '__init__', claims)
    monkeypatch.setattr(NodeClaims, 'claim', dispatch)
    for driver in e.mission.drivers.values():
        monkeypatch.setattr(driver, 'run', native)
    monkeypatch.setattr(e.hub, 'start', native)
    monkeypatch.setattr(e.hub, 'control', native)
    return seen


def exercise(e, monkeypatch, caplog, capsys, launch_attempts, *, stage,
             fault_type, error_number, status, expected_type, message):
    filename = str(e.hub.directory / FILENAME_MARKER)
    filename2 = str(e.hub.directory / FILENAME2_MARKER)
    raw_message = (MESSAGE_MARKER + ' cwd=' + str(Path.cwd()) + ' mission=' + e.ident
                   + ' node=' + e.node['node_id'] + ' selected=' + e.node['secret']
                   + ' foreign=' + FOREIGN_SECRET)
    fault = fault_type(error_number, raw_message, filename, None, filename2)
    assert type(fault) is fault_type and fault.filename == filename and fault.filename2 == filename2
    seen = trace_exact_recheck(e, monkeypatch, stage=stage, fault=fault, expected_type=expected_type)
    before, before_physical = state(e), physical(e)
    code, reply = call(e, body=BODY)  # Original actual registered Node credential.
    captured = capsys.readouterr()
    channels = {'body': json.dumps(reply, ensure_ascii=False), 'log': caplog.text,
                'stdout': captured.out, 'stderr': captured.err}
    excluded = {'absolute_hub': str(e.hub.directory), 'absolute_cwd': str(Path.cwd()),
                'requested_mission': e.ident, 'registered_node': e.node['node_id'],
                'registered_secret': e.node['secret'], 'foreign_synthetic_secret': FOREIGN_SECRET,
                'other_registered_secret': e.other['secret'], 'exception_message': raw_message,
                'exception_filename': filename, 'exception_filename2': filename2,
                'message_marker': MESSAGE_MARKER, 'filename_marker': FILENAME_MARKER,
                'filename2_marker': FILENAME2_MARKER}
    leaks = {name: {channel: token in output for channel, output in channels.items()}
             for name, token in excluded.items()}
    after, after_physical = state(e), physical(e)
    error = reply.get('error', {})
    diagnostic = error.get('diagnostic_id')
    chain = e.mission.store.verify_event_chain()
    receipt = {'classification': 'ACTUAL_AUTHENTICATED_LATE_RECHECK_HTTP_TEST_ONLY',
               'stage': stage, 'http_requests': 1, 'http_status': code,
               'error_type': error.get('type'), 'diagnostic_id': diagnostic,
               'diagnostic_correlated_if500': code != 500 or diagnostic in caplog.text,
               'message_sha256': hashlib.sha256(str(error.get('message')).encode()).hexdigest(),
               'observed_boundaries': seen, 'excluded_token_present_by_channel': leaks,
               'logical_state_unchanged': after == before,
               'nonauxiliary_bytes_and_names_unchanged': after_physical[0] == before_physical[0],
               'physical_auxiliary_names_before': before_physical[1],
               'physical_auxiliary_names_after': after_physical[1],
               'node_claims_initialized': e.mission._node_claims is not None,
               'remote_directory_exists': (e.mission.directory / 'remote').exists(),
               'core_native_reservations': len(e.mission.journal.runs()),
               'event_chain_valid': chain['valid'], 'subprocess_attempts': launch_attempts['subprocess'],
               'session_scope': 'zero at auth exit; one actual cached Hub session at handler admission',
               'auxiliary_oracle': 'recorded separately; no zero transient WAL/shm or cold-session oracle'}
    with (e.root / 'late-auth-path-case.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')

    # Boundary/auth/state facts are checked independently before prospective
    # diagnostics. RED has already retained all facts, including leak booleans.
    checks, sessions, auths, inodes = (1, 0, 1, 2) if stage == 'auth-exit' else (3, 1, 2, 5)
    assert seen['credential_compare'] == auths
    assert seen['credential_results'] == [True] * auths
    assert seen['registered_credential_arguments'] == [True] * auths
    assert seen['auth_calls'] == auths and seen['auth_returns'] == (0 if stage == 'auth-exit' else 2)
    assert seen['rechecks'] == checks and seen['faults'] == 1
    assert seen['directory_inode'] == seen['database_inode'] == inodes
    assert seen['approved_spec'] == auths
    assert seen['session_calls'] == seen['session_completed'] == sessions
    assert seen['real_session_identity'] is bool(sessions)
    if sessions:
        assert seen['trace'].index('real_session_return') < seen['trace'].index('database_inode_fault:' + stage)
    assert all(seen[name] == 0 for name in ['node_claims_property', 'registry_constructor',
               'claims_constructor', 'backend_dispatch', 'native_or_controller_dispatch'])
    assert launch_attempts['subprocess'] == 0
    assert after == before and after_physical[0] == before_physical[0]
    assert not e.mission.journal.runs() and chain['valid']
    assert e.mission._node_claims is None and not (e.mission.directory / 'remote').exists()
    assert set(reply) == {'error'} and set(error) == {'type', 'message', 'diagnostic_id'}
    assert re.fullmatch(r'ng_[0-9a-f]{24}', diagnostic)
    if code == 500:
        assert diagnostic in caplog.text
    assert code == status
    assert error['type'] == expected_type.__name__ and error['message'] == message
    assert seen['escaped_recheck_exact_builtin']
    assert not any(present for channels in leaks.values() for present in channels.values()), 'late recheck diagnostic exposed private synthetic data'


def test_real_auth_exit_oserror_is_fixed403_before_any_hub_session(
        env, monkeypatch, caplog, capsys, retained_loopback_no_native):
    exercise(env, monkeypatch, caplog, capsys, retained_loopback_no_native,
             stage='auth-exit', fault_type=OSError, error_number=errno.EIO,
             status=403, expected_type=PermissionError, message=OS_MESSAGE)


def test_real_handler_recheck_absent_is_fixed404_after_one_actual_session_before_backend(
        env, monkeypatch, caplog, capsys, retained_loopback_no_native):
    exercise(env, monkeypatch, caplog, capsys, retained_loopback_no_native,
             stage='handler-admission', fault_type=FileNotFoundError, error_number=errno.ENOENT,
             status=404, expected_type=FileNotFoundError, message=ABSENT_MESSAGE)
