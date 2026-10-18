"""Bounded N4 node-only loopback sidecar, not an operator or execution API.

NodeGateway(hub, *, port=0) uses the hub's fixed bound mission selection. Node
authentication reuses NodeRegistry.authenticate against an existing read-only
connection, WITHOUT running the registry constructor or opening a hub session.
Transport operations use only documented NodeClaims methods. Missing transport
services fail explicitly; this gateway never supplies fake ACKs, expires work on
readback, completes core reservations, starts a controller, or invokes a driver.

JSON responses wrap the unchanged transport result in
{controller_mission_id, result}. Heartbeat may also deliver controls at this
outer level; delivery is separate from native ACK. Input responses are bytes.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields
import hashlib
import hmac
import inspect
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

from ..autonomy.policy import IdempotencyConflictError, LeaseLost, NotFoundError
from .lead_console import approved_spec
from .node_registry import NodeRegistry, validate_request_id
from .protocol import Receipt, redact

MAX_JSON_BYTES = 1_500_000
MAX_UPLOAD_BYTES = 8_000_000
MAX_URI_BYTES = 16_384
MAX_HEADER_BYTES = 16_384
MAX_JSON_DEPTH = 64
MAX_JSON_ITEMS = 50_000
MAX_REQUESTS = 16
MAX_RESPONSE_BYTES = 4_000_000
_MISSION = r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}'
_CLAIM = r'claim_[0-9a-f]{32}'
_NODE = re.compile(r'node_[0-9a-f]{32}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_NODE_CREDENTIAL = re.compile(r'(?i)\bNode\s+[0-9a-f]{64}(?![A-Za-z0-9._~-])')
_PREFIX = re.compile(r'/node/v1/(' + _MISSION + r')/(.*)\Z')
_FILE_ROUTE = re.compile(r'(inputs|uploads)/(' + _CLAIM + r')/([1-9][0-9]{0,18})\Z')
_HEADERS = {'host', 'authorization', 'x-sisyfus-node', 'content-length', 'content-type',
            'accept', 'accept-encoding', 'user-agent', 'connection'}
_CONTROL_FILES = {'autonomy.sqlite3', 'autonomy.sqlite3-wal', 'autonomy.sqlite3-shm',
                  'auth.json', 'credentials', 'credentials.json', 'config.toml', 'id_rsa', 'id_ed25519'}
_EVENT_FIELDS = {
    'process_started': {'pid', 'driver'},
    'model_identity': {'requested_model', 'actual_model', 'telemetry'},
    'session_bound': {'session_id'}, 'turn_bound': {'session_id', 'turn_id'},
    'native_event': {'method', 'params'}, 'approval_denied': {'method', 'request_id'},
    'control_ack': {'command_id', 'accepted'},
}
_LOG = logging.getLogger(__name__)


class _AuthenticationError(PermissionError):
    """Missing or incorrect node credentials (401, not operator authority)."""


class _ReadOnlyStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    @contextmanager
    def _transaction(self, *, immediate: bool = True):
        if immediate:
            raise RuntimeError('node authentication is strictly read-only')
        yield self.db


class _RegistryReader(NodeRegistry):
    def __init__(self, db: sqlite3.Connection):
        # Only the public authenticate method is used. The normal constructor
        # intentionally creates schema/namespace and belongs AFTER admission.
        self.journal = SimpleNamespace(store=_ReadOnlyStore(db))


@dataclass(frozen=True)
class _Identity:
    directory: Path
    directory_inode: tuple[int, int]
    database_inode: tuple[int, int]


def _inode(path: Path, *, directory: bool = False) -> tuple[int, int]:
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise PermissionError('selected control resource must be regular and non-symlink')
    return info.st_dev, info.st_ino


def _control_resource(read: Any, *args: Any, **kwargs: Any) -> Any:
    """Sanitize OS failures only at the fixed control-resource IO boundary."""
    try:
        return read(*args, **kwargs)
    except (FileNotFoundError, NotADirectoryError):
        raise FileNotFoundError('selected mission has no bound control database') from None
    except OSError:
        raise PermissionError('selected control resource is unavailable') from None


def _auth(hub: Any, mission_id: str, node_id: str, secret: str) -> _Identity:
    """Read only the fixed hub child, bound spec, and existing node identity.

    mode=ro sees current WAL revocations (immutable=1 would miss them). No
    AutonomyStore, Journal, NodeRegistry initialization, or hub session here.
    Recheck inode bindings so an exchanged child/database grants no admission.
    """
    try:
        directory = hub.path(mission_id)
    except ValueError as exc:
        raise PermissionError('selected mission is not a fixed hub child') from exc
    database = directory / 'autonomy.sqlite3'
    directory_inode = _control_resource(_inode, directory, directory=True)
    database_inode = _control_resource(_inode, database)
    try:
        _control_resource(approved_spec, directory)
    except ValueError as exc:
        raise FileNotFoundError('selected mission has no bound specification') from exc
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        schema = db.execute("SELECT value FROM metadata WHERE key='remote_node_schema'").fetchone()
        if not schema or schema[0] != '1':
            raise _AuthenticationError('node is not registered in the selected mission')
        reader = _RegistryReader(db)
        if not reader.authenticate(node_id, secret):
            row = db.execute('SELECT status,credential_digest FROM remote_nodes WHERE node_id=?', (node_id,)).fetchone()
            if (row and hmac.compare_digest(row['credential_digest'], reader._credential(node_id, secret))
                    and row['status'] == 'REVOKED'):
                raise PermissionError('node identity is revoked')
            raise _AuthenticationError('node credentials are missing or incorrect')
        if db.execute("SELECT 1 FROM metadata WHERE key IN "
                      "('techlead:inbox_policy:trial-child','techlead:learning_config:trial')").fetchone():
            raise PermissionError('node transport is excluded for trial children')
        learning = db.execute("SELECT data_json FROM events WHERE event_type='LEAD_LEARNING_FROZEN' LIMIT 1").fetchone()
        if learning:
            manifest = json.loads(learning[0])
            if manifest.get('split') in {'search', 'holdout'} or not str(manifest.get('pair_id', 'standalone:')).startswith('standalone:'):
                raise PermissionError('node transport is excluded for trial children')
    finally:
        db.close()
    identity = _Identity(directory, directory_inode, database_inode)
    _check_identity(identity)
    return identity


def _check_identity(identity: _Identity) -> None:
    if (_control_resource(_inode, identity.directory, directory=True) != identity.directory_inode
            or _control_resource(_inode, identity.directory / 'autonomy.sqlite3') != identity.database_inode):
        raise PermissionError('selected control resource changed during authentication')


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _clean(value: Any, secret: str = '') -> Any:
    """Node credentials need an explicit scrub in addition to protocol.redact.

    Unknown input is never echoed by parsers. This also sanitizes internal
    diagnostics. Credential-bearing transport data is rejected rather than
    rewritten: N1 must hash the actual admitted record for immutable replay.
    """
    value = redact(value)
    if isinstance(value, dict):
        return {_clean(k, secret): _clean(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v, secret) for v in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[REDACTED]')
        return _NODE_CREDENTIAL.sub('Node [REDACTED]', value)
    return value


def _has_credential(value: Any, secret: str) -> bool:
    if isinstance(value, str):
        return bool(secret in value or _NODE_CREDENTIAL.search(value))
    if isinstance(value, dict):
        return any(_has_credential(key, secret) or _has_credential(child, secret) for key, child in value.items())
    if isinstance(value, list):
        return any(_has_credential(child, secret) for child in value)
    return False


def _shape(value: Any, required: set[str], label: str, optional: set[str] | None = None) -> None:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise ValueError(label + ' has invalid fields')


def _json_limits(value: Any, depth: int = 0, count: list[int] | None = None) -> None:
    count = [0] if count is None else count
    count[0] += 1
    if depth > MAX_JSON_DEPTH or count[0] > MAX_JSON_ITEMS:
        raise ValueError('JSON nesting or item count exceeds bound')
    if isinstance(value, str):
        value.encode('utf-8')
    elif value is None or isinstance(value, (int, bool)):
        return
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('JSON numbers must be finite')
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError('JSON keys must be text')
            key.encode('utf-8')
            _json_limits(child, depth + 1, count)
    elif isinstance(value, list):
        for child in value:
            _json_limits(child, depth + 1, count)
    else:
        raise ValueError('invalid JSON value')


@dataclass(frozen=True)
class _Response:
    """Private detached snapshot plus the exact, already validated wire bytes."""
    envelope: dict[str, Any]
    raw: bytes


def _finalize_response(mission_id: str, result: Any, secret: str,
                       controls: Any = None) -> _Response:
    # This validator is controller-pure: no store, clock, IO or model authority.
    # Fresh mutations call it INSIDE their own transaction; historical readbacks
    # still use it at publication without backfill, cleanup or lease renewal.
    envelope = {'controller_mission_id': mission_id, 'result': result}
    if controls is not None:
        envelope['controls'] = controls
    try:
        _json_limits(envelope)
        if _clean(envelope, secret) != envelope:
            raise ValueError('unclean response')
        raw = _json_bytes(envelope)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('oversize response')
        # A JSON roundtrip detaches every nested object. Later mutations to the
        # callback's copies cannot alter either this snapshot or its wire bytes.
        return _Response(json.loads(raw), raw)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise RuntimeError('transport response is not representable') from None


def _preflight_receipt_response(body: dict[str, Any], secret: str) -> None:
    """Proved body-only lower bounds, never an invented full-view estimate."""
    try:
        native = Receipt(**body['receipt'])
        complete = {field.name: getattr(native, field.name) for field in fields(Receipt)}
        receipt_raw = _json_bytes(complete)
        tree_raw = _json_bytes(body['tree'])
        # Match the existing public service's normalized receipt/raw-tree caps.
        # Redaction must not make otherwise invalid raw evidence admissible.
        if len(receipt_raw) > 1_000_000 or len(tree_raw) > 1_000_000:
            raise ValueError('oversize evidence')
        receipt = redact(json.loads(receipt_raw))
        manifest = sorted(body['manifest'], key=lambda entry: entry['path'])
        tree = redact(json.loads(tree_raw))
        counts = []
        for value, start_depth in ((receipt, 2), (manifest, 2), (tree, 2)):
            if _clean(value, secret) != value:
                raise ValueError('unclean evidence')
            count = [0]
            _json_limits(value, depth=start_depth, count=count)
            counts.append(count[0])
        # Disjoint envelope/view/mission, R/M/T, and uploads list containing at
        # least every STORED manifest row (dict + four values). Keys count zero.
        floor = 3 + sum(counts) + 1 + 5 * len(manifest)
        if floor > MAX_JSON_ITEMS:
            raise ValueError('item floor exceeds response')
        # Only disjoint, actually stored fragments; immutable offer/request
        # overhead is unknown here and is validated by the transaction callback.
        if sum(len(_json_bytes(value)) for value in (receipt, manifest, tree)) > MAX_RESPONSE_BYTES:
            raise ValueError('byte floor exceeds response')
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('receipt response exceeds bounded JSON or contains credential material') from None


def _epoch(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError('epoch must be a positive bounded integer')
    return value


def _text(value: Any, label: str, limit: int = 1000, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value.strip() and not empty) or len(value.encode()) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(label + ' must be bounded text without controls')
    return value


def _relative(value: Any) -> str:
    value = _text(value, 'path')
    if '\\' in value or ':' in value:
        raise ValueError('invalid relative path')
    if any(not part or part.startswith('.') or part.casefold() in _CONTROL_FILES or len(part.encode()) > 255 for part in value.split('/')):
        raise ValueError('path contains a control or dot component')
    return value


def _entries(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 128:
        raise ValueError('manifest must contain at most 128 files')
    aliases: dict[str, str] = {}
    names = set()
    total = 0
    for entry in value:
        _shape(entry, {'path', 'sha256', 'size'}, 'manifest entry')
        path = _relative(entry['path'])
        if not isinstance(entry['sha256'], str) or not _HASH.fullmatch(entry['sha256']):
            raise ValueError('manifest requires lowercase SHA256')
        size = entry['size']
        if type(size) is not int or not 0 <= size <= MAX_UPLOAD_BYTES:
            raise ValueError('manifest file size exceeds bound')
        total += size
        if path in names:
            raise ValueError('duplicate manifest path')
        names.add(path)
        parts = path.split('/')
        for end in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:end])
            if prefix.casefold() in aliases and aliases[prefix.casefold()] != prefix:
                raise ValueError('manifest component alias')
            aliases[prefix.casefold()] = prefix
    if total > 32_000_000 or len(_json_bytes(value)) > 200_000:
        raise ValueError('manifest total exceeds bound')
    if any('/'.join(p.split('/')[:i]) in names for p in names for i in range(1, len(p.split('/')))):
        raise ValueError('manifest file/directory collision')


def _tree(value: Any) -> None:
    _shape(value, {'schema', 'files', 'tree', 'errors', 'complete'}, 'tree')
    if type(value['schema']) is not int or value['schema'] != 1 or type(value['complete']) is not bool:
        raise ValueError('tree requires schema 1 and boolean complete')
    _entries(value['files'])
    if not isinstance(value['tree'], list) or len(value['tree']) > 4096 or not isinstance(value['errors'], list) or len(value['errors']) > 4096:
        raise ValueError('tree enumeration exceeds bound')
    for item in value['tree']:
        _shape(item, {'path', 'kind'}, 'tree entry', {'sha256', 'size'})
        # Diagnostic paths (hidden/control/non-regular) remain evidence, not IO
        # authority. Do not require safe transferable paths or missing hashes.
        _text(item['path'], 'tree path')
        if not isinstance(item['kind'], str) or item['kind'] not in {'file', 'directory', 'symlink', 'fifo', 'socket', 'device'}:
            raise ValueError('invalid tree kind')
        if 'sha256' in item and (not isinstance(item['sha256'], str) or not _HASH.fullmatch(item['sha256'])):
            raise ValueError('invalid tree SHA256')
        if 'size' in item and (type(item['size']) is not int or not 0 <= item['size'] <= 2**63 - 1):
            raise ValueError('invalid tree size')
    for issue in value['errors']:
        _shape(issue, {'code', 'path'}, 'tree diagnostic')
        _text(issue['code'], 'tree diagnostic code', 200)
        _text(issue['path'], 'tree diagnostic path', empty=True)


def _native_receipt(value: Any) -> None:
    _shape(value, {'status'}, 'receipt', {f.name for f in fields(Receipt)} - {'status'})
    if not isinstance(value['status'], str) or value['status'] not in {'COMPLETED', 'ERROR', 'INTERRUPTED', 'UNKNOWN'}:
        raise ValueError('invalid native receipt status')
    if 'output' in value and not isinstance(value['output'], str) or 'usage' in value and not isinstance(value['usage'], dict):
        raise ValueError('receipt requires text output and object usage')
    if value.get('exit_code') is not None and type(value['exit_code']) is not int:
        raise ValueError('receipt exit_code must be integer or null')
    for name in ('session_id', 'turn_id', 'error', 'requested_model', 'actual_model'):
        if value.get(name) is not None and not isinstance(value[name], str):
            raise ValueError('receipt optional text has invalid type')
    if value.get('requested_model') not in (None, 'gpt-6.1-sol') or len(_json_bytes(value)) > 1_000_000:
        raise ValueError('receipt model or size differs from transport bounds')


def _events(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError('sync batch requires at most 100 events')
    for item in value:
        _shape(item, {'seq', 'kind', 'data'}, 'sync event')
        _epoch(item['seq'])
        kind, data = item['kind'], item['data']
        if not isinstance(kind, str) or kind not in _EVENT_FIELDS:
            raise ValueError('invalid native event kind')
        _shape(data, _EVENT_FIELDS[kind], 'native event data', {'error'} if kind == 'control_ack' else set())
        text_fields = {
            'model_identity': ('telemetry',), 'session_bound': ('session_id',),
            'turn_bound': ('session_id', 'turn_id'), 'native_event': ('method',),
            'approval_denied': ('method',), 'control_ack': ('command_id',),
        }.get(kind, ())
        for key in text_fields:
            _text(data[key], 'native event identifier', MAX_JSON_BYTES)
        if kind == 'process_started' and (type(data['pid']) is not int or data['pid'] <= 0 or data['driver'] != 'codex'):
            raise ValueError('process event requires positive pid and codex driver')
        if kind == 'model_identity':
            if data['requested_model'] != 'gpt-6.1-sol':
                raise ValueError('model event differs from pinned native model')
            if data['actual_model'] is not None:
                _text(data['actual_model'], 'actual model', MAX_JSON_BYTES)
        if kind == 'native_event' and not isinstance(data['params'], dict):
            raise ValueError('native event params must be an object')
        if kind == 'approval_denied' and type(data['request_id']) is not int:
            _text(data['request_id'], 'approval request identifier', MAX_JSON_BYTES)
        if kind == 'control_ack' and (type(data['accepted']) is not bool or data.get('error') is not None and not isinstance(data['error'], dict)):
            raise ValueError('control acknowledgement requires boolean and optional error object')
        if len(_json_bytes(item)) > 64_000:
            raise ValueError('sync event exceeds 64000 UTF-8 bytes')
    if len(_json_bytes(value)) > 1_000_000:
        raise ValueError('sync batch exceeds 1000000 UTF-8 bytes')


def _body_schema(operation: str, body: Any) -> None:
    if operation == 'claim':
        _shape(body, {'request_id'}, 'claim')
        validate_request_id(body['request_id'])
        if redact(body['request_id']) != body['request_id']:
            raise ValueError('request_id contains credential material')
        return
    required = {'claim_id', 'epoch'}
    if operation == 'sync': required |= {'events'}
    if operation == 'receipt': required |= {'receipt', 'manifest', 'tree'}
    _shape(body, required, operation)
    if not isinstance(body['claim_id'], str) or not re.fullmatch(_CLAIM, body['claim_id']):
        raise ValueError('invalid claim_id')
    _epoch(body['epoch'])
    if operation == 'sync': _events(body['events'])
    if operation == 'receipt':
        _native_receipt(body['receipt'])
        _entries(body['manifest'])
        _tree(body['tree'])


def _method(backend: Any, name: str):
    method = getattr(backend, name, None)
    if not callable(method):
        raise RuntimeError('node transport service is not installed: ' + name)
    return method


def _admitting_method(backend: Any, name: str):
    method = _method(backend, name)
    try:
        parameter = inspect.signature(method).parameters.get('admit_response')
    except (ValueError, TypeError):
        parameter = None
    if parameter is None or parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
        raise RuntimeError(name + ' response admission requires named keyword-only admit_response')
    return method


class NodeGateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # One budget from handler setup through headers, body and response. Hosts
    # may shorten it via a subclass; the constructor keeps a finite ceiling.
    request_timeout = 5.0

    def __init__(self, hub: Any, *, port: int = 0):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('port must be an integer in [0,65535]')
        if (type(self.request_timeout) not in {int, float}
                or not math.isfinite(self.request_timeout) or not 0 < self.request_timeout <= 30):
            raise ValueError('request_timeout must be finite seconds in (0,30]')
        self.request_timeout = float(self.request_timeout)
        self.hub = hub
        self._requests = threading.BoundedSemaphore(MAX_REQUESTS)
        super().__init__(('127.0.0.1', port), _Handler)

    def process_request(self, request, client_address) -> None:
        if not self._requests.acquire(blocking=False):
            try:
                deadline = time.monotonic() + min(.05, self.request_timeout)
                request.settimeout(max(.001, deadline - time.monotonic()))
                raw = _json_bytes({'error': {'type': 'ServiceBusy', 'message': 'node request concurrency bound reached'}})
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: '
                                + str(len(raw)).encode() + b'\r\n\r\n' + raw)
                request.shutdown(socket.SHUT_WR)
                # A client may still be sending its framed body. Immediate
                # close with unread bytes resets the peer before it reads 503.
                # Drain only a bounded amount/time, never parse or dispatch it.
                remaining_bytes = MAX_HEADER_BYTES
                while remaining_bytes and (remaining := deadline - time.monotonic()) > 0:
                    request.settimeout(remaining)
                    try:
                        chunk = request.recv(min(4096, remaining_bytes))
                    except (TimeoutError, ConnectionResetError):
                        break
                    if not chunk:
                        break
                    remaining_bytes -= len(chunk)
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._requests.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._requests.release()

    def handle_error(self, request, client_address) -> None:
        # Socket disconnects and HTTP parser failures must not emit a default
        # traceback that may include an untrusted request or credential value.
        exc = sys.exception()
        _LOG.error('node_gateway_socket_failure diagnostic_id=ng_%s type=%s',
                   secrets.token_hex(12), type(exc).__name__)

    @property
    def url(self) -> str:
        return 'http://127.0.0.1:' + str(self.server_port)


class _ConnectionDeadline(Exception):
    """Close-only outcome: an expired transport cannot acknowledge/reject IO."""


class _Handler(BaseHTTPRequestHandler):
    server: NodeGateway

    def setup(self) -> None:
        started = time.monotonic()
        self._secret = ''
        super().setup()
        self._deadline = started + self.server.request_timeout
        self.connection.settimeout(min(5, self.server.request_timeout))
        # Buffered header readline/body read can receive arbitrarily many
        # individually timely bytes. A separate whole-connection timer shuts
        # down this socket, unblocking every recv without renewing the budget.
        self._deadline_timer = threading.Timer(max(0, self._deadline - time.monotonic()),
                                                self._expire_connection)
        self._deadline_timer.name = 'node-gateway-deadline'
        self._deadline_timer.daemon = True
        try:
            self._deadline_timer.start()
        except BaseException:
            self._deadline_timer.cancel()
            self._deadline_timer = None
            super().finish()
            raise

    def _expire_connection(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # A completed/disconnected peer may race the deadline callback.

    def finish(self) -> None:
        # Join before closing file wrappers so a late callback never outlives
        # its connection or retains request/timer state after a fast response.
        timer = self._deadline_timer
        timer.cancel()
        timer.join()
        self._deadline_timer = None
        super().finish()

    def _check_deadline(self) -> None:
        if time.monotonic() >= self._deadline:
            self._expire_connection()
            raise _ConnectionDeadline('connection deadline exceeded')

    def log_message(self, *_args: Any) -> None:
        pass  # No request line, path, Authorization or payload access logging.

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # The stdlib default echoes unknown methods/request lines as HTML.
        self._send({'error': {'type': 'ValueError', 'message': 'invalid HTTP request'}}, 400 if code != 501 else 404)

    def _send(self, value: Any, status: int = 200, *, binary: bool = False) -> None:
        try:
            self._check_deadline()
        except _ConnectionDeadline:
            return
        raw = value if binary else value.raw if isinstance(value, _Response) else _json_bytes(value)
        if not binary and len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError('transport response exceeds bounded JSON output')
        self.send_response(status)
        self.send_header('Content-Type', 'application/octet-stream' if binary else 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Connection', 'close')
        # Serialization/header preparation can cross the budget even when
        # the Timer callback is delayed. Check before each actual wire write.
        try:
            self._check_deadline()
        except _ConnectionDeadline:
            return
        self.end_headers()
        self.close_connection = True
        try:
            self._check_deadline()
        except _ConnectionDeadline:
            return
        self.wfile.write(raw)

    def _headers(self) -> tuple[str, str]:
        hosts = self.headers.get_all('Host', [])
        if len(hosts) != 1 or hosts[0] not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
            raise PermissionError('invalid loopback Host')
        if self.headers.get_all('Origin', []):
            raise PermissionError('Origin is forbidden on node routes')
        auth = self.headers.get_all('Authorization', [])
        nodes = self.headers.get_all('X-Sisyfus-Node', [])
        if len(auth) != 1 or len(nodes) != 1 or not _NODE.fullmatch(nodes[0]):
            raise _AuthenticationError('one Node authorization and node identity are required')
        match = re.fullmatch(r'Node ([0-9a-f]{64})', auth[0])
        if not match:
            raise _AuthenticationError('Node credentials are required, not operator Bearer')
        self._secret = secret = match[1]
        items = list(self.headers.raw_items())
        if len(items) > 32 or sum(len(k) + len(v) + 4 for k, v in items) > MAX_HEADER_BYTES:
            raise ValueError('headers exceed bound')
        seen = set()
        for key, value in items:
            name = key.lower()
            if name not in _HEADERS or name in seen or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError('unsupported, repeated or malformed header')
            seen.add(name)
        return nodes[0], secret

    def _target(self) -> tuple[str, str, str]:
        # Inspect the original request target too: BaseHTTPRequestHandler
        # normalizes a leading // before the application sees self.path.
        raw_target = self.requestline.split()[1]
        if not raw_target.isascii() or len(raw_target) > MAX_URI_BYTES or not raw_target.startswith('/') or raw_target.startswith('//') or '#' in raw_target or any(ord(c) < 33 or ord(c) == 127 for c in raw_target):
            raise ValueError('invalid or oversized URI')
        path, separator, query = raw_target.partition('?')
        if re.search(r'%(?![0-9a-fA-F]{2})', raw_target):
            raise ValueError('invalid URI percent encoding')
        match = _PREFIX.fullmatch(path)
        if not match:
            raise FileNotFoundError('unknown fixed node route')
        if _clean(match[1], self._secret) != match[1]:
            raise FileNotFoundError('unknown fixed node route')
        return match[1], match[2], query if separator else ''

    def _route(self, tail: str, query: str) -> tuple[str, str | None, int | None, dict[str, str]]:
        try:
            values = parse_qs(query, keep_blank_values=True, strict_parsing=True, encoding='utf-8', errors='strict', max_num_fields=2)
        except (ValueError, UnicodeError):
            raise ValueError('invalid URI query') from None
        if any(len(v) != 1 for v in values.values()):
            raise ValueError('duplicate query field')
        params = {k: v[0] for k, v in values.items()}
        if self.command == 'POST' and tail in {'claim', 'sync', 'heartbeat', 'status', 'receipt'}:
            if params:
                raise ValueError('JSON node routes accept no query')
            return tail, None, None, params
        file_route = _FILE_ROUTE.fullmatch(tail)
        if file_route and self.command == ('GET' if file_route[1] == 'inputs' else 'PUT'):
            operation, claim_id = file_route[1], file_route[2]
            epoch = _epoch(int(file_route[3]))
            if set(params) != ({'path'} if operation == 'inputs' else {'path', 'sha256'}):
                raise ValueError('invalid file query fields')
            _relative(params['path'])
            if self._secret in params['path']:
                raise ValueError('file path contains node credential material')
            if operation == 'uploads' and not _HASH.fullmatch(params['sha256']):
                raise ValueError('upload requires lowercase SHA256')
            return operation, claim_id, epoch, params
        raise FileNotFoundError('unknown fixed node method or route')

    def _read(self, operation: str) -> Any:
        lengths = self.headers.get_all('Content-Length', [])
        if operation == 'inputs' and not lengths:
            return None
        if len(lengths) != 1 or not re.fullmatch(r'0|[1-9][0-9]{0,9}', lengths[0]):
            raise ValueError('one exact Content-Length is required')
        length = int(lengths[0])
        limit = MAX_UPLOAD_BYTES if operation == 'uploads' else MAX_JSON_BYTES
        if length > limit or operation == 'inputs' and length != 0:
            raise ValueError('body exceeds route bound')
        if operation == 'inputs':
            return None
        types = self.headers.get_all('Content-Type', [])
        expected = 'application/octet-stream' if operation == 'uploads' else 'application/json'
        if len(types) != 1 or types[0].lower() not in {expected, expected + '; charset=utf-8'} or operation == 'uploads' and types[0].lower() != expected:
            raise ValueError('invalid Content-Type for node operation')
        try:
            raw = self.rfile.read(length)
        except TimeoutError as exc:
            raise ValueError('body was not received within the bounded timeout') from exc
        if len(raw) != length:
            raise ValueError('body differs from Content-Length')
        if operation == 'uploads':
            if self._secret.encode() in raw or _NODE_CREDENTIAL.search(raw.decode('latin1')):
                raise ValueError('upload contains node credential material')
            return raw

        def pairs(items):
            value = {}
            for key, child in items:
                if key in value:
                    raise ValueError('duplicate JSON field')
                value[key] = child
            return value

        def constant(_value):
            raise ValueError('JSON numbers must be finite')

        try:
            body = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
            _json_limits(body)
            _body_schema(operation, body)
        except (UnicodeError, RecursionError, OverflowError, json.JSONDecodeError) as exc:
            raise ValueError('invalid bounded UTF-8 JSON object') from exc
        return body

    def _request(self) -> None:
        try:
            self._check_deadline()
            node_id, secret = self._headers()
            mission_id, tail, query = self._target()
            identity = _auth(self.server.hub, mission_id, node_id, secret)
            operation, claim_id, epoch, params = self._route(tail, query)
            body = self._read(operation)
            if operation not in {'inputs', 'uploads'} and _has_credential(body, secret):
                raise ValueError('transport data contains node credential material')
            if operation == 'receipt':
                _preflight_receipt_response(body, secret)
            if operation == 'uploads' and hashlib.sha256(body).hexdigest() != params['sha256']:
                raise ValueError('upload SHA256 mismatch')
            # Validate the body before opening a writable backend. Repeat auth
            # after bounded reading to fence revocation while a body is in flight.
            if _auth(self.server.hub, mission_id, node_id, secret) != identity:
                raise PermissionError('selected mission identity changed')
            self._check_deadline()
            session = self.server.hub._session(mission_id)
            _check_identity(identity)
            self._check_deadline()
            if Path(session.mission.journal.store.path).absolute() != identity.directory / 'autonomy.sqlite3':
                raise PermissionError('hub session differs from authenticated control database')
            backend = session.mission.node_claims
            if _auth(self.server.hub, mission_id, node_id, secret) != identity:
                raise PermissionError('selected mission identity changed')
            self._check_deadline()
            captured = None

            def admit_response(detached_result, detached_controls):
                nonlocal captured
                if ((operation == 'heartbeat' and not isinstance(detached_controls, list))
                        or (operation != 'heartbeat' and detached_controls is not None)):
                    raise RuntimeError('transport response is not representable')
                captured = _finalize_response(mission_id, detached_result, secret, detached_controls)

            if operation == 'claim':
                result = _admitting_method(backend, 'claim')(node_id, body['request_id'], admit_response=admit_response)
            elif operation in {'sync', 'heartbeat', 'status', 'receipt'}:
                args = [node_id, body['claim_id'], body['epoch']]
                if operation == 'sync':
                    result = _admitting_method(backend, 'sync')(*args, body['events'], admit_response=admit_response)
                elif operation == 'receipt':
                    result = _admitting_method(backend, 'receipt')(*args, body['receipt'],
                        body['manifest'], tree=body['tree'], admit_response=admit_response)
                elif operation == 'heartbeat':
                    result = _admitting_method(backend, 'heartbeat')(*args, admit_response=admit_response)
                else:
                    result = _method(backend, 'status')(*args)
            elif operation == 'inputs':
                view = _method(backend, 'status')(node_id, claim_id, epoch)
                entry = next((item for item in view['input_manifest']['files'] if item['path'] == params['path']), None)
                if entry is None:
                    raise FileNotFoundError('input is absent from the fixed snapshot manifest')
                result = _method(backend, 'read_input')(node_id, claim_id, epoch, params['path'])
                if not isinstance(result, bytes) or len(result) != entry['size'] or hashlib.sha256(result).hexdigest() != entry['sha256']:
                    raise RuntimeError('input service returned bytes differing from the fixed manifest')
            else:
                result = _admitting_method(backend, 'upload')(node_id, claim_id, epoch, params['path'],
                    params['sha256'], body, admit_response=admit_response)
            # No revoked identity receives a readback if it raced service IO.
            if _auth(self.server.hub, mission_id, node_id, secret) != identity:
                raise PermissionError('selected mission identity changed')
            self._check_deadline()
            if operation == 'inputs':
                if not isinstance(result, bytes) or len(result) > MAX_UPLOAD_BYTES:
                    raise RuntimeError('input service did not return bounded bytes')
                if secret.encode() in result:
                    raise RuntimeError('input service returned node credential material')
                self._send(result, binary=True)
            else:
                if captured is None:
                    if operation == 'heartbeat':
                        raise RuntimeError('heartbeat response admission did not capture controls')
                    # Cached/readonly results are never rebound/revalidated by
                    # the service. Old unpublishable facts stay retained as-is.
                    captured = _finalize_response(mission_id, result, secret)
                else:
                    returned = {'controller_mission_id': mission_id, 'result': result}
                    if 'controls' in captured.envelope:
                        returned['controls'] = captured.envelope['controls']
                    try:
                        if _json_bytes(returned) != captured.raw:
                            raise ValueError('returned result differs from admitted snapshot')
                    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
                        raise RuntimeError('transport response is not representable') from None
                self._send(captured)
        except _ConnectionDeadline:
            raise  # Never translate a possible committed operation into HTTP 400.
        except Exception as exc:
            if isinstance(exc, _AuthenticationError): status = 401
            elif isinstance(exc, PermissionError): status = 403
            elif isinstance(exc, (FileNotFoundError, NotFoundError)): status = 404
            elif isinstance(exc, (LeaseLost, IdempotencyConflictError)): status = 409
            elif isinstance(exc, (ValueError, UnicodeError)): status = 400
            elif isinstance(exc, OSError) and 'operation' in locals() and operation in {'inputs', 'uploads'}: status = 409
            else: status = 500
            diagnostic_id = 'ng_' + secrets.token_hex(12)
            message = str(_clean(str(exc), getattr(self, '_secret', '')))[:2000]
            message = ''.join(c if ord(c) >= 32 and ord(c) != 127 else '[CONTROL]' for c in message)
            if status == 500:
                _LOG.error('node_gateway_failure diagnostic_id=%s type=%s message=%s', diagnostic_id, type(exc).__name__, message)
            self._send({'error': {'type': type(exc).__name__, 'message': message,
                                  'diagnostic_id': diagnostic_id}}, status)

    def do_GET(self) -> None:
        self._request()

    def do_POST(self) -> None:
        self._request()

    def do_PUT(self) -> None:
        self._request()
