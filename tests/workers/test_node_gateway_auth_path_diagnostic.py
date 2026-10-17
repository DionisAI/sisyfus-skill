"""Frozen TEST-ONLY precredential path diagnostics, real ephemeral loopback.

Source e01e: _headers -> _target -> _auth; _auth performs directory inode,
database inode, approved_spec before the readonly credential comparison. The
rare-OS delegates raise only at the exact selected existing resource boundary.
No successful backend double, error alias, native call or old-test modification.
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
from test_node_gateway import call, env, forbidden_native, gateway_type, state


# Install the original unmodified guard before any fixture or network activity.
sys.addaudithook(runpy.run_path(str(Path(__file__).resolve().parents[2] /
                    'scripts/test_retained.py'), run_name='auth_path_retained_guard')['guard_deletion'])

MISSING = 'auth_path_missing_fixture_0001'
EMPTY = 'auth_path_empty_fixture_0001'
UNKNOWN_NODE = 'node_' + '8' * 32
WRONG_SECRET = '9' * 64
FOREIGN_SECRET = '7' * 64
MESSAGE_MARKER = 'AUTH_PATH_OS_MESSAGE_MUST_STAY_PRIVATE'
FILENAME_MARKER = 'AUTH_PATH_OS_FILENAME_MUST_STAY_PRIVATE'
FILENAME2_MARKER = 'AUTH_PATH_OS_FILENAME2_MUST_STAY_PRIVATE'
ABSENT_MESSAGE = 'selected mission has no bound control database'
OS_MESSAGE = 'selected control resource is unavailable'
BODY = {'request_id': 'auth_path_diagnostic_0001'}

FAULTS = [
    ('directory', PermissionError, errno.EACCES, 403, 'PermissionError', OS_MESSAGE),
    ('database', NotADirectoryError, errno.ENOTDIR, 404, 'FileNotFoundError', ABSENT_MESSAGE),
    ('database', OSError, errno.EIO, 403, 'PermissionError', OS_MESSAGE),
    ('spec', FileNotFoundError, errno.ENOENT, 404, 'FileNotFoundError', ABSENT_MESSAGE),
    ('spec', NotADirectoryError, errno.ENOTDIR, 404, 'FileNotFoundError', ABSENT_MESSAGE),
    ('spec', OSError, errno.EIO, 403, 'PermissionError', OS_MESSAGE),
]


@pytest.fixture(autouse=True)
def retained_loopback_no_native(tmp_path_factory, monkeypatch):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'explicit isolated loopback opt-in required'
    assert type(tmp_path_factory).__name__ == 'RetainedPaths', 'use the unchanged retained runner'
    monkeypatch.setattr(subprocess, 'Popen', forbidden_native)


def physical(e):
    content = {}
    auxiliary = []
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


def guard_and_trace(e, monkeypatch, fault=None):
    observed = {'auth': 0, 'directory_inode': 0, 'database_inode': 0,
                'approved_spec': 0, 'credential_compare': 0,
                'faults': 0, 'lazy_session': 0, 'registry_constructor': 0}
    real_auth, real_inode = module._auth, module._inode
    real_spec, real_compare = module.approved_spec, module._RegistryReader.authenticate

    @wraps(real_auth)
    def auth(*args, **kwargs):
        observed['auth'] += 1
        return real_auth(*args, **kwargs)

    @wraps(real_inode)
    def inode(path, *, directory=False):
        boundary = None
        if path == e.mission.directory and directory:
            boundary = 'directory'
        elif path == e.mission.directory / 'autonomy.sqlite3' and not directory:
            boundary = 'database'
        if boundary:
            observed[boundary + '_inode'] += 1
        if fault and boundary == fault[0]:
            observed['faults'] += 1
            raise fault[1]
        return real_inode(path, directory=directory)

    @wraps(real_spec)
    def spec(directory):
        observed['approved_spec'] += 1
        if fault and fault[0] == 'spec' and directory == e.mission.directory:
            observed['faults'] += 1
            raise fault[1]
        return real_spec(directory)

    @wraps(real_compare)
    def compare(reader, *args, **kwargs):
        observed['credential_compare'] += 1
        return real_compare(reader, *args, **kwargs)

    def lazy(*args, **kwargs):
        observed['lazy_session'] += 1
        return forbidden_native(*args, **kwargs)

    def registry(*args, **kwargs):
        observed['registry_constructor'] += 1
        return forbidden_native(*args, **kwargs)

    monkeypatch.setattr(module, '_auth', auth)
    monkeypatch.setattr(module, '_inode', inode)
    monkeypatch.setattr(module, 'approved_spec', spec)
    monkeypatch.setattr(module._RegistryReader, 'authenticate', compare)
    monkeypatch.setattr(module.NodeRegistry, '__init__', registry)
    monkeypatch.setattr(e.hub, '_session', lazy)
    return observed


def assertions_and_retained_receipt(e, replies, before, before_physical, observed,
        caplog, capsys, *, status, kind, message, mission_id, extras=(), compare=0, faults=0):
    captured = capsys.readouterr()
    wire = json.dumps(replies, ensure_ascii=False)
    output = wire + caplog.text + captured.out + captured.err
    excluded = {
        'absolute_hub': str(e.hub.directory), 'absolute_cwd': str(Path.cwd()),
        'requested_mission': mission_id, 'requested_node': UNKNOWN_NODE,
        'selected_node_secret': WRONG_SECRET, 'other_synthetic_secret': FOREIGN_SECRET,
        'registered_fixture_secret': e.node['secret'], 'other_registered_fixture_secret': e.other['secret'],
        'exception_message_marker': MESSAGE_MARKER,
        'exception_filename_marker': FILENAME_MARKER, 'exception_filename2_marker': FILENAME2_MARKER,
    }
    excluded.update({'exception_component_' + str(index): value for index, value in enumerate(extras)})
    leaks = {name: value in output for name, value in excluded.items() if value}
    after, after_physical = state(e), physical(e)
    # Capture actual HTTP and zero-backend facts BEFORE any prospective-contract
    # assertion; RED retains evidence even when status/type/content fails early.
    receipt = {
        'classification': 'ACTUAL_PUBLIC_NEGATIVE_HTTP_NO_NATIVE_NOT_ACCEPTANCE',
        'http_statuses': [reply[0] for reply in replies],
        'error_types': [reply[1].get('error', {}).get('type') for reply in replies],
        'diagnostic_ids': [reply[1].get('error', {}).get('diagnostic_id') for reply in replies],
        'message_sha256': [hashlib.sha256(str(reply[1].get('error', {}).get('message')).encode()).hexdigest()
                           for reply in replies],
        'observed_boundaries': observed, 'excluded_token_present': leaks,
        'logical_state_unchanged': after == before,
        'nonauxiliary_bytes_and_names_unchanged': after_physical[0] == before_physical[0],
        'physical_auxiliary_names_before': before_physical[1],
        'physical_auxiliary_names_after': after_physical[1],
        'lazy_backend_initialized': e.mission._node_claims is not None,
        'remote_directory_exists': (e.mission.directory / 'remote').exists(),
        'core_native_reservations': len(e.mission.journal.runs()),
        'event_chain_valid': e.mission.store.verify_event_chain()['valid'],
        'native_invocations': 0,
        'auxiliary_oracle': 'recorded separately; no claim of zero transient WAL/shm activity',
    }
    with (e.root / 'auth-path-case.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    assert after == before
    assert after_physical[0] == before_physical[0]
    assert e.mission._node_claims is None and not (e.mission.directory / 'remote').exists()
    assert not e.mission.journal.runs() and receipt['event_chain_valid']
    assert observed['lazy_session'] == observed['registry_constructor'] == 0
    assert observed['credential_compare'] == compare and observed['faults'] == faults
    for code, reply in replies:
        assert set(reply) == {'error'}
        error = reply['error']
        assert set(error) == {'type', 'message', 'diagnostic_id'}
        assert re.fullmatch(r'ng_[0-9a-f]{24}', error['diagnostic_id'])
        if code == 500:
            assert error['diagnostic_id'] in caplog.text
        assert code == status
        assert error['type'] == kind
        assert error['message'] == message
    assert not any(leaks.values()), 'precredential diagnostic exposed a retained private token'


@pytest.mark.parametrize('resource', ['missing', 'empty'])
def test_genuine_missing_fixed_resource_is_content_free404_before_credentials(
        env, monkeypatch, caplog, capsys, resource):
    e = env
    selected = MISSING if resource == 'missing' else EMPTY
    if resource == 'empty':
        (e.hub.directory / selected).mkdir()
    else:
        assert not (e.hub.directory / selected).exists()
    observed = guard_and_trace(e, monkeypatch)
    before, before_physical = state(e), physical(e)
    node = {'node_id': UNKNOWN_NODE, 'secret': WRONG_SECRET}
    replies = [call(e, target='/node/v1/' + selected + '/claim', body=BODY, node=node) for _ in range(2)]
    assert observed['auth'] == 2 and observed['approved_spec'] == 0
    assertions_and_retained_receipt(e, replies, before, before_physical, observed, caplog, capsys,
        status=404, kind='FileNotFoundError', message=ABSENT_MESSAGE, mission_id=selected)


@pytest.mark.parametrize('boundary,exception_type,error_number,status,kind,message', FAULTS,
                         ids=['inode-directory-permission', 'inode-database-notdirectory',
                              'inode-database-oserror-twofilenames', 'spec-missing',
                              'spec-notdirectory', 'spec-oserror-twofilenames'])
def test_exact_precredential_os_boundary_sanitizes_builtin_type_and_all_channels(
        env, monkeypatch, caplog, capsys, boundary, exception_type, error_number, status, kind, message):
    e = env
    filename = str(e.hub.directory / FILENAME_MARKER)
    filename2 = str(e.hub.directory / FILENAME2_MARKER)
    raw_message = (MESSAGE_MARKER + ' cwd=' + str(Path.cwd()) + ' mission=' + e.ident
                   + ' node=' + UNKNOWN_NODE + ' selected=' + WRONG_SECRET + ' foreign=' + FOREIGN_SECRET)
    fault = exception_type(error_number, raw_message, filename, None, filename2)
    assert type(fault) is exception_type and fault.filename == filename and fault.filename2 == filename2
    observed = guard_and_trace(e, monkeypatch, (boundary, fault))
    before, before_physical = state(e), physical(e)
    replies = [call(e, body=BODY, node={'node_id': UNKNOWN_NODE, 'secret': WRONG_SECRET}) for _ in range(2)]
    assertions_and_retained_receipt(e, replies, before, before_physical, observed, caplog, capsys,
        status=status, kind=kind, message=message, mission_id=e.ident,
        extras=(filename, filename2, raw_message), faults=2)


@pytest.mark.parametrize('identity', ['registered-wrong-secret', 'unknown-node'])
def test_original_readonly_identity401_stays_content_free_before_lazy(
        env, monkeypatch, caplog, capsys, identity):
    e = env
    observed = guard_and_trace(e, monkeypatch)
    before, before_physical = state(e), physical(e)
    node = {'node_id': e.node['node_id'] if identity == 'registered-wrong-secret' else UNKNOWN_NODE,
            'secret': WRONG_SECRET}
    assert WRONG_SECRET != e.node['secret'] and WRONG_SECRET != e.other['secret']
    replies = [call(e, body=BODY, node=node) for _ in range(2)]
    assertions_and_retained_receipt(e, replies, before, before_physical, observed, caplog, capsys,
        status=401, kind='_AuthenticationError', message='node credentials are missing or incorrect',
        mission_id=e.ident, extras=(node['node_id'],), compare=2)


@pytest.mark.parametrize('boundary,status,kind,message', [
    ('host', 403, 'PermissionError', 'invalid loopback Host'),
    ('origin', 403, 'PermissionError', 'Origin is forbidden on node routes'),
    ('credential-shape', 401, '_AuthenticationError', 'Node credentials are required, not operator Bearer'),
    ('header-bound', 400, 'ValueError', 'headers exceed bound'),
])
def test_original_host_origin_header_and_bound_precedence_never_reaches_path_auth(
        env, monkeypatch, caplog, capsys, boundary, status, kind, message):
    e = env
    observed = guard_and_trace(e, monkeypatch)
    before, before_physical = state(e), physical(e)
    headers = {'host': [('Host', 'untrusted-auth-path.invalid:1')],
        'origin': [('Origin', 'http://untrusted-auth-path.invalid')],
        'credential-shape': [('Authorization', 'Node malformed-auth-path-value')],
        'header-bound': [('User-Agent', 'x' * module.MAX_HEADER_BYTES)]}[boundary]
    replies = [call(e, target='/node/v1/' + MISSING + '/claim', body=BODY,
                    node={'node_id': UNKNOWN_NODE, 'secret': WRONG_SECRET}, headers=headers)]
    assert observed['auth'] == observed['directory_inode'] == observed['database_inode'] == observed['approved_spec'] == 0
    assertions_and_retained_receipt(e, replies, before, before_physical, observed, caplog, capsys,
        status=status, kind=kind, message=message, mission_id=MISSING,
        extras=('untrusted-auth-path.invalid', 'malformed-auth-path-value'))
