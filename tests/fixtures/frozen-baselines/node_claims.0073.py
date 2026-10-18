"""Bounded, disconnected Remote Node v1 transport sidecar; NOT task evidence.

NodeClaims(journal, registry, artifact_root, lease_seconds=30, *, clock=time.time)
uses the same mission autonomy.sqlite3 and hash chain. clock returns finite UTC
Unix seconds and may be injected for deterministic testing. No native execution,
core completion, verdict, integration, network or command API exists here.

offer(run_key, node_id, request, input_manifest) pins a Request or exact Request
field dict (optional driver='codex'). v1 requires codex/gpt-6.1-sol/workspace-write,
a matching real IN_FLIGHT reservation and, when present, its frozen context and
role. Manifest shape: {'files': [{'path': str, 'sha256': lower_hex, 'size': int}],
'output_paths': [str]}. Input files are verified in request.cwd; output_paths
are the immutable controller upload allowlist, not required success evidence.
No paths beginning with dots or credential/control filenames are transferable.

offer/get return {mission_id, run_key, node_id, task_id, driver, request,
prompt_hash, input_manifest, input_manifest_hash, fingerprint, status, claim_id,
epoch, lease_expires_at, created_at, receipt, manifest, uploads}. get returns
None for an unknown run. Statuses: OFFERED, CLAIMED, UNKNOWN, RECEIPTED,
RECONCILIATION_CANDIDATE. epoch is 0 before claim and 1 thereafter; NEVER reissued.
claim(node_id, request_id) returns {mission_id, node_id, request_id, status,
claim}; status is CLAIMED or NO_WORK, claim is an offer projection or None.
Its durable response snapshot is replayed exactly, including NO_WORK, and is
NOT renewed permission to execute after expiry. Query/heartbeat checks currency.
Fresh claims return durable NO_WORK while any same-store canonical run is
UNKNOWN or remote offer is UNKNOWN/RECONCILIATION_CANDIDATE. Queued offers
remain OFFERED; cached responses and canonical core status are unchanged.
heartbeat returns the current offer projection. expire returns projections of
newly UNKNOWN offers; expiry/revocation/core loss NEVER requeues or settles core.

sync(node_id, claim_id, epoch, events) accepts only a list of exact
{seq: positive int (not bool, <= 2**63-1), kind: str, data: dict} records.
Sequences within a batch are increasing and contiguous; new records begin at
the durable high-water mark + 1. A contiguous stored prefix may be replayed
before appending. Stored seq requires the identical normalized RAW record SHA;
only its digest, kind and REDACTED data are retained in remote_event_sync.
Accepted kinds/required data fields: process_started(pid: positive int,
driver: 'codex'); model_identity(requested_model: 'gpt-6.1-sol', actual_model:
nonempty str or None, telemetry: nonempty str); session_bound(session_id:
nonempty str); turn_bound(session_id, turn_id: nonempty str); native_event
(method: nonempty str, params: dict); approval_denied(method: nonempty str,
request_id: int except bool or nonempty str); control_ack(command_id: nonempty
str, accepted: bool, optional error: dict or None). Extra fields are rejected.
Nested data requires finite JSON/string keys, at most 64 levels. Limits:
100 records, 64_000 UTF-8 bytes/normalized raw record, 1_000_000 bytes/batch.
Returns {mission_id, run_key, node_id, claim_id, epoch, last_seq,
lease_expires_at}, a transport acknowledgement, NOT execution permission.
Empty/all-duplicate batches are read-only and still require live ownership.
Fresh records, Journal.event_in/after_event, control ACK and node lease renewal
share one transaction/hash chain; any failure rolls back the ENTIRE batch.
Original node deadline and canonical continuation are rechecked after callbacks
and before commit; renewal never rescues an expired lease. Call expire explicitly
after a rejected late sync; no automatic expiry write or requeue occurs here.
Sequence metadata never enters native acceptance data or settles a receipt.

Controller-only bind_input_snapshot(run_key, root, manifest) pins a prepared
absolute NOFOLLOW snapshot BEFORE a first offer. Returns {mission_id, run_key,
root, manifest, manifest_hash, reservation_fingerprint}. An identical binding
is read-only even after ownership loss; it is NOT a new execution grant.
Different root/manifest/run identity or historical backfill raises
IdempotencyConflictError. Bound offers verify this snapshot rather than mutable
Request.cwd; legacy unbound offers keep their existing behavior.
read_input(node_id, claim_id, epoch, path) returns bytes only from the fixed
manifest, rechecks ALL package hashes/sizes and pinned regular/single-link
descriptors, then uses a NEW read transaction to recheck node/core leases and
identity after IO. No renewal/expiry/write occurs. Missing binding/path raises
FileNotFoundError; filesystem/integrity failures are explicit OSError/ValueError.
status(node_id, claim_id, epoch) reads the historical owner's view, including
stored tree ONLY when present; it never checks/renews/expires a deadline or grants
execution. ACTIVE authentication belongs to the gateway; foreign nodes and
incorrect epochs still fail. Durable RECEIPTED survives natural node expiry.
withdraw(run_key, reason) changes only unclaimed OFFERED/epoch 0 to WITHDRAWN;
same reason replays, changed reason conflicts, all ever-claimed states read back.
Reason is nonempty bounded text (2_000 bytes), persisted redacted plus raw digest.
post_controls(run_key, controls) is controller-only, returns [{id, action, text,
status}]. Exact wire fields: {id: nonempty ASCII identity <=200 bytes,
action:'interrupt', text:''}; at most 100 records/32_000 UTF-8 bytes per batch
and 100 outstanding controls per run. IDs are globally write-once per mission.
pending_controls(node_id, claim_id, epoch) reads [{id, action, text}] from live
own claims without marking delivery/renewing. New same-run control_ack events
advance PENDING to ACK/REJECTED in the N1 transaction; unknown/foreign IDs grant
no authority. Cached events do not repeat ACKs or hooks.
receipt(..., *, tree=...) optionally pins {schema:1, files, tree, errors,
complete:bool} from full_tree_manifest, WITHOUT importing remote_artifacts.
Tree is write-once in the same receipt transaction: raw digest for conflicts,
redacted full report at rest. New receipt/status return tree only when supplied/
present; old get and no-tree receipt projections stay EXACT, never backfilled.
Malformed shape/types/finite JSON/bounds fail before expiry or receipt mutation.
Bounds: 128 files, 4096 observed nodes/errors, 1000 UTF-8 bytes/path, 128 bytes/
kind/code, 64 bytes/hash, 1_000_000 bytes/report. File sizes are diagnostic
nonnegative int64, not proof that bytes are transferable. Nonregular/unsafe
paths, missing tree hashes, reported errors/incompleteness and semantic hash/
table mismatches remain terminal transport DATA for controller INVALID checks;
they are NEVER materialized or approved here. Only uploaded STORED bytes enter
the unchanged manifest verification. Optional tree never changes native
UNKNOWN/late/PREPARING semantics or completes a canonical run.

upload(node_id, claim_id, epoch, path, sha256, data: bytes) returns
{path, sha256, size, status: 'STORED'}. Path must be in output_paths; size is
len(data), bounded below. receipt(..., receipt, manifest) accepts Receipt or
an exact Receipt field dict. Timely manifests must match ALL uploads, each
STORED. Late/revoked/core-lost receipts match exactly the STORED subset and
become RECONCILIATION_CANDIDATE; the receipt event names incomplete_paths.
Only STORED bytes are reverified; PREPARING files remain fenced and untouched.
It returns the offer projection. Timely native UNKNOWN stays UNKNOWN.
Even RECEIPTED means transport only: Journal.complete is NEVER called.
Identical receipt replay reads back; changed receipts/uploads raise
IdempotencyConflictError. Wrong nodes/revoked active actions raise PermissionError;
epoch/lease/core mismatches raise LeaseLost; malformed inputs raise ValueError.

Bounds: 128 input files and 128 output paths/uploads, 8 MB/file, 32 MB/package,
200 KB/manifest, 200 KB/prompt, 1 MB UTF-8/receipt, 64 nested JSON levels.
Receipt field types and finite JSON with string keys are validated before
mutation; malformed fields, JSON, UTF-8 or size raise ValueError.
All creation is exclusive and
retained; a durable PREPARING upload precedes filesystem writes. Interrupted
uploads recover ONLY if the existing file matches, otherwise remain fenced;
partial/unrecognized files are never overwritten or removed. Artifact roots
are pinned per mission; descriptor-relative O_NOFOLLOW traversal fences symlinks.
HTTP authentication and remote agent/driver integration are still pending.
"""
from __future__ import annotations

from dataclasses import asdict, fields
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Any, Callable

from ..autonomy.models import canonical_json, utc_now
from ..autonomy.policy import IdempotencyConflictError, LeaseLost
from .node_registry import NodeRegistry, validate_request_id
from .protocol import Receipt, Request, bounded, digest, redact

MAX_FILES = 128
MAX_FILE_BYTES = 8_000_000
MAX_TOTAL_BYTES = 32_000_000
MAX_MANIFEST_BYTES = 200_000
MAX_RECEIPT_BYTES = 1_000_000
MAX_SYNC_EVENTS = 100
MAX_SYNC_EVENT_BYTES = 64_000
MAX_SYNC_BATCH_BYTES = 1_000_000
MAX_TRANSPORT_CONTROLS = 100
MAX_CONTROL_BATCH_BYTES = 32_000
MAX_TREE_ENTRIES = 4096
MAX_TREE_BYTES = 1_000_000
_TRANSPORT_ID = re.compile(r'[A-Za-z0-9_.:-]{1,200}\Z')
_NO_TREE = object()
_SYNC_FIELDS = {
    'process_started': {'pid', 'driver'},
    'model_identity': {'requested_model', 'actual_model', 'telemetry'},
    'session_bound': {'session_id'},
    'turn_bound': {'session_id', 'turn_id'},
    'native_event': {'method', 'params'},
    'approval_denied': {'method', 'request_id'},
    'control_ack': {'command_id', 'accepted'},
}
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_CONTROL = {'autonomy.sqlite3', 'autonomy.sqlite3-wal', 'autonomy.sqlite3-shm',
            'auth.json', 'credentials', 'credentials.json', 'config.toml', 'id_rsa', 'id_ed25519'}


def _sync_json(value: Any, depth: int = 0) -> None:
    """Validate before canonical_json (which otherwise stringifies objects)."""
    if depth > 64:
        raise ValueError('sync JSON nesting exceeds bound')
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for child in value.values():
            _sync_json(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _sync_json(child, depth + 1)
    else:
        raise ValueError('sync requires finite JSON with string keys')


def _sync_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _sync_fields(kind: str, data: dict[str, Any]) -> None:
    required = _SYNC_FIELDS[kind]
    optional = {'error'} if kind == 'control_ack' else set()
    if not required <= set(data) or set(data) - required - optional:
        raise ValueError('sync data differs from native emit fields')
    text_fields = {
        'model_identity': ('telemetry',), 'session_bound': ('session_id',),
        'turn_bound': ('session_id', 'turn_id'), 'native_event': ('method',),
        'approval_denied': ('method',), 'control_ack': ('command_id',),
    }.get(kind, ())
    if any(not _sync_text(data[k]) for k in text_fields):
        raise ValueError('sync native identifiers must be nonempty text without controls')
    if kind == 'process_started' and (type(data['pid']) is not int or data['pid'] <= 0 or data['driver'] != 'codex'):
        raise ValueError('sync process requires positive pid and codex driver')
    if kind == 'model_identity' and (data['requested_model'] != 'gpt-6.1-sol'
                                    or data['actual_model'] is not None and not _sync_text(data['actual_model'])):
        raise ValueError('sync model identity differs from pinned native model')
    if kind == 'native_event' and not isinstance(data['params'], dict):
        raise ValueError('sync native params must be a dict')
    if kind == 'approval_denied' and type(data['request_id']) is not int and not _sync_text(data['request_id']):
        raise ValueError('sync approval request identity must be int except bool or nonempty text')
    if kind == 'control_ack' and (type(data['accepted']) is not bool
                                 or data.get('error') is not None and not isinstance(data['error'], dict)):
        raise ValueError('sync control acknowledgement requires bool and optional error dict')


def _sync_batch(events: Any) -> list[dict[str, Any]]:
    """Detach and hash raw normalized input; only redacted payloads survive."""
    if not isinstance(events, list) or len(events) > MAX_SYNC_EVENTS:
        raise ValueError('sync requires a list of at most 100 events')
    result = []
    size = 2 + max(0, len(events) - 1)  # Normalized list brackets and commas.
    previous = None
    try:
        for item in events:
            if not isinstance(item, dict) or set(item) != {'seq', 'kind', 'data'}:
                raise ValueError('sync event requires seq, kind and data only')
            seq, kind, data = item['seq'], item['kind'], item['data']
            if type(seq) is not int or not 1 <= seq <= 2**63 - 1:
                raise ValueError('sync seq must be a positive bounded integer except bool')
            if previous is not None and seq != previous + 1:
                raise ValueError('sync batch sequences must be increasing and contiguous')
            if not isinstance(kind, str) or kind not in _SYNC_FIELDS or not isinstance(data, dict):
                raise ValueError('sync accepts current Codex emit kinds with dict data only')
            _sync_fields(kind, data)
            _sync_json(data)
            encoded = canonical_json(item).encode('utf-8')
            if len(encoded) > MAX_SYNC_EVENT_BYTES:
                raise ValueError('sync event exceeds 64_000 UTF-8 bytes')
            size += len(encoded)
            if size > MAX_SYNC_BATCH_BYTES:
                raise ValueError('sync batch exceeds 1_000_000 UTF-8 bytes')
            raw = json.loads(encoded)
            result.append({'seq': seq, 'kind': kind, 'raw_digest': hashlib.sha256(encoded).hexdigest(),
                           'data_json': canonical_json(redact(raw['data']))})
            previous = seq
    except (TypeError, RecursionError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid sync JSON') from exc
    return result


def _receipt_payload(value: Receipt | dict[str, Any]) -> dict[str, Any]:
    """Validate untrusted fields before hashing, deep copying or DB mutation."""
    names = {f.name for f in fields(Receipt)}
    # asdict() recursively copies usage, so it is not an input validator:
    # cyclic/deep/unsupported telemetry must first get an explicit ValueError.
    raw = {name: getattr(value, name) for name in names} if isinstance(value, Receipt) else dict(value) if isinstance(value, dict) else None
    if raw is None or set(raw) - names:
        raise ValueError('terminal transport requires native Receipt fields only')
    try:
        native = Receipt(**raw)
    except TypeError as exc:
        raise ValueError('invalid native Receipt') from exc
    raw = {name: getattr(native, name) for name in names}
    for name in ('status', 'output'):
        if not isinstance(raw[name], str):
            raise ValueError(f'receipt {name} must be text')
    if not isinstance(raw['usage'], dict):
        raise ValueError('receipt usage must be a dict')
    if raw['exit_code'] is not None and type(raw['exit_code']) is not int:
        raise ValueError('receipt exit_code must be an integer except bool, or None')
    for name in ('session_id', 'turn_id', 'error', 'requested_model', 'actual_model'):
        if raw[name] is not None and not isinstance(raw[name], str):
            raise ValueError(f'receipt {name} must be text or None')
    if raw['status'] not in {'COMPLETED', 'ERROR', 'INTERRUPTED', 'UNKNOWN'}:
        raise ValueError('invalid terminal native status')
    if raw['requested_model'] not in {None, 'gpt-6.1-sol'}:
        raise ValueError('receipt requested model differs from pinned v1 model')

    def json_value(item: Any, depth: int = 0) -> None:
        if depth > 64:
            raise ValueError('receipt JSON nesting exceeds bound')
        if item is None or isinstance(item, (str, int, bool)):
            return
        if isinstance(item, float) and math.isfinite(item):
            return
        if isinstance(item, dict) and all(isinstance(k, str) for k in item):
            for child in item.values():
                json_value(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                json_value(child, depth + 1)
        else:
            raise ValueError('receipt requires finite JSON with string keys')

    try:
        json_value(raw)
        encoded = canonical_json(raw).encode('utf-8')
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise ValueError('receipt exceeds bound')
        # Detach the validated JSON snapshot; no caller-owned nested references.
        return json.loads(encoded)
    except (TypeError, RecursionError, OverflowError) as exc:
        raise ValueError('invalid receipt JSON') from exc


def _admit_transport_credentials(value: Any, depth: int = 0) -> None:
    """Screen bounded admission data using Gateway's exact Node token syntax.

    protocol.redact does not cover these credentials. Reject, never rewrite,
    before a binding/offer can become an immutable, unreturnable transport row.
    No Gateway import: it already depends on this service through the Hub.
    """
    if depth > 64:
        raise ValueError('transport admission nesting exceeds bound')
    if isinstance(value, str):
        if re.search(r'(?i)\bNode\s+[0-9a-f]{64}(?![A-Za-z0-9._~-])', value):
            raise ValueError('transport admission contains node credential material')
    elif isinstance(value, dict):
        for key, child in value.items():
            _admit_transport_credentials(key, depth + 1)
            _admit_transport_credentials(child, depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _admit_transport_credentials(child, depth + 1)


def _transport_key(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > 200:
        raise ValueError('transport run_key must identify a canonical reservation')
    return value


def _transport_root(value: Any) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError('snapshot root must be a controller absolute path')
    root = Path(value)
    if not root.is_absolute() or '..' in root.parts or '\x00' in str(root) or len(str(root).encode('utf-8')) > 4000:
        raise ValueError('snapshot root must be an absolute non-parent path')
    return root


def _transport_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {'files', 'output_paths'}:
        raise ValueError('snapshot manifest requires files and output_paths only')
    files_ = _entries(value['files'])
    outputs = value['output_paths']
    if not isinstance(outputs, list) or len(outputs) > MAX_FILES:
        raise ValueError('snapshot output path count exceeds bound')
    outputs = [_path(p) for p in outputs]
    if len(set(outputs)) != len(outputs):
        raise ValueError('duplicate snapshot output path')
    _paths([f['path'] for f in files_] + outputs)
    result = {'files': files_, 'output_paths': sorted(outputs)}
    if len(canonical_json(result).encode('utf-8')) > MAX_MANIFEST_BYTES:
        raise ValueError('snapshot manifest exceeds bound')
    return result


def _snapshot_stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _snapshot_read(root: Path, files_: list[dict[str, Any]], selected: str | None = None) -> bytes | None:
    """Pin one root across ALL bounded reads; never follow or read special files."""
    root_fd = _directory(root)
    try:
        root_stamp = _snapshot_stamp(os.fstat(root_fd))
        result = None
        for item in files_:
            parts = item['path'].split('/')
            parent = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    os.close(parent)
                    parent = nxt
                before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= MAX_FILE_BYTES:
                    raise ValueError('snapshot input requires a bounded single-link regular file')
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    stamp = _snapshot_stamp(before)
                    if _snapshot_stamp(os.fstat(fd)) != stamp:
                        raise ValueError('snapshot input changed before read')
                    chunks, size, sha = [], 0, hashlib.sha256()
                    while chunk := os.read(fd, 65536):
                        size += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise ValueError('snapshot input exceeds file bound')
                        sha.update(chunk)
                        if item['path'] == selected:
                            chunks.append(chunk)
                    if (size != before.st_size or _snapshot_stamp(os.fstat(fd)) != stamp
                            or _snapshot_stamp(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)) != stamp):
                        raise ValueError('snapshot input changed during read')
                    if (sha.hexdigest(), size) != (item['sha256'], item['size']):
                        raise ValueError('snapshot bytes differ from fixed hash/size')
                    if item['path'] == selected:
                        result = b''.join(chunks)
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
        current = _directory(root)
        try:
            if _snapshot_stamp(os.fstat(root_fd)) != root_stamp or _snapshot_stamp(os.fstat(current)) != root_stamp:
                raise ValueError('snapshot root changed during read')
        finally:
            os.close(current)
        return result
    finally:
        os.close(root_fd)


def _tree_payload(value: Any) -> tuple[str, str]:
    """Wire/type bounds only: retain integrity diagnostics, never approve a tree."""
    def text(item: Any, bound: int, *, empty: bool = False) -> None:
        if not isinstance(item, str) or not empty and not item or len(item.encode('utf-8')) > bound:
            raise ValueError('tree text field exceeds type/UTF-8 bound')

    def size(item: Any) -> None:
        if type(item) is not int or not 0 <= item <= 2**63 - 1:
            raise ValueError('tree size must be nonnegative int64 except bool')

    if (not isinstance(value, dict) or set(value) != {'schema', 'files', 'tree', 'errors', 'complete'}
            or type(value['schema']) is not int or value['schema'] != 1 or type(value['complete']) is not bool):
        raise ValueError('tree requires the exact full_tree_manifest schema')
    try:
        for key, bound in [('files', MAX_FILES), ('tree', MAX_TREE_ENTRIES), ('errors', MAX_TREE_ENTRIES)]:
            if not isinstance(value[key], list) or len(value[key]) > bound:
                raise ValueError('tree entry count/type exceeds bound')
        for item in value['files']:
            if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'size'}:
                raise ValueError('tree file requires path, sha256 and size')
            text(item['path'], 1000); text(item['sha256'], 64); size(item['size'])
        for item in value['tree']:
            if (not isinstance(item, dict) or not {'path', 'kind'} <= set(item)
                    or set(item) - {'path', 'kind', 'sha256', 'size'}):
                raise ValueError('tree node requires path/kind and optional hash/size only')
            text(item['path'], 1000); text(item['kind'], 128)
            if 'sha256' in item:
                text(item['sha256'], 64)
            if 'size' in item:
                size(item['size'])
        for item in value['errors']:
            if not isinstance(item, dict) or set(item) != {'code', 'path'}:
                raise ValueError('tree diagnostic requires code/path only')
            text(item['code'], 128); text(item['path'], 1000, empty=True)
        _sync_json(value)
        raw = canonical_json(value).encode('utf-8')
        if len(raw) > MAX_TREE_BYTES:
            raise ValueError('tree report exceeds 1_000_000 UTF-8 bytes')
        return hashlib.sha256(raw).hexdigest(), canonical_json(redact(json.loads(raw)))
    except (TypeError, RecursionError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid tree JSON/UTF-8') from exc


def _control_payload(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_TRANSPORT_CONTROLS:
        raise ValueError('controls require a list of at most 100 interrupts')
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'id', 'action', 'text'}:
            raise ValueError('control requires id/action/text only')
        if (not isinstance(item['id'], str) or not _TRANSPORT_ID.fullmatch(item['id'])
                or item['id'] != redact(item['id']) or not isinstance(item['action'], str)
                or item['action'] != 'interrupt' or not isinstance(item['text'], str) or item['text'] != ''):
            raise ValueError('control requires fixed identity, interrupt action and empty text')
        if item['id'] not in seen:
            result.append(dict(item))
            seen.add(item['id'])
    if len(canonical_json(value).encode('utf-8')) > MAX_CONTROL_BATCH_BYTES:
        raise ValueError('control batch exceeds UTF-8 bound')
    return result


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 1000:
        raise ValueError('artifact path must be 1..1000 UTF-8 bytes')
    parts = value.split('/')
    if '\\' in value or ':' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('invalid artifact path')
    if any(not p or p.startswith('.') or p.casefold() in _CONTROL or len(p.encode()) > 255 for p in parts):
        raise ValueError('relative artifact path contains a control or dot component')
    return value


def _paths(paths: list[str]) -> None:
    # Check component aliases too: A/x and a/y collide on case-folding hosts.
    seen: dict[str, str] = {}
    files = set(paths)
    for path in paths:
        _path(path)
        parts = path.split('/')
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i])
            folded = prefix.casefold()
            if folded in seen and seen[folded] != prefix:
                raise ValueError('case-folded artifact path collision')
            seen[folded] = prefix
            if i < len(parts) and prefix in files:
                raise ValueError('artifact file/directory collision')


def _entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_FILES:
        raise ValueError('manifest file count exceeds bound')
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'size'}:
            raise ValueError('manifest file requires path, sha256 and size only')
        path = _path(item['path'])
        if not isinstance(item['sha256'], str) or not _HASH.fullmatch(item['sha256']):
            raise ValueError('manifest requires lowercase SHA256')
        if type(item['size']) is not int or not 0 <= item['size'] <= MAX_FILE_BYTES:
            raise ValueError('manifest file size exceeds bound')
        result.append(dict(item, path=path))
    paths = [i['path'] for i in result]
    if len(set(paths)) != len(paths):
        raise ValueError('duplicate manifest path')
    _paths(paths)
    if sum(i['size'] for i in result) > MAX_TOTAL_BYTES or len(canonical_json(result).encode()) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest total exceeds bound')
    return sorted(result, key=lambda i: i['path'])


def _directory(path: Path, *, create: bool = False) -> int:
    """Open every absolute component without following symlinks, retain on error."""
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('root must be an absolute, non-parent path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass  # Existing directory still must pass NOFOLLOW below.
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _parent(root: Path, relative: str, *, create: bool = False) -> tuple[int, str]:
    fd = _directory(root, create=create)
    parts = relative.split('/')
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def _file_metadata(fd: int) -> dict[str, Any]:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES:
        raise ValueError('artifact must be a bounded, unlinked regular file')
    sha = hashlib.sha256()
    size = 0
    while chunk := os.read(fd, 65536):
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise ValueError('artifact exceeds file size bound')
        sha.update(chunk)
    return {'sha256': sha.hexdigest(), 'size': size}


def _verify_file(root: Path, item: dict[str, Any]) -> None:
    parent, name = _parent(root, item['path'])
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            actual = _file_metadata(fd)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    if actual != {'sha256': item['sha256'], 'size': item['size']}:
        raise ValueError('retained artifact hash/size mismatch')


class NodeClaims:
    def __init__(self, journal: Any, registry: NodeRegistry, artifact_root: str | Path,
                 lease_seconds: float = 30, *, clock: Callable[[], float] = time.time):
        if Path(journal.store.path).resolve() != Path(registry.journal.store.path).resolve():
            raise ValueError('registry and claims must share the mission store')
        self.journal, self.registry = journal, registry
        self.artifact_root = Path(artifact_root).absolute()
        self.lease_seconds = bounded(lease_seconds, .05, 3600, 'lease_seconds')
        self.clock = clock
        self._now()
        fd = _directory(self.artifact_root, create=True)
        os.close(fd)
        with journal.store._transaction() as db:
            schema = db.execute("SELECT value FROM metadata WHERE key='remote_claim_schema'").fetchone()
            if schema and schema[0] != '1':
                raise ValueError('incompatible remote claim schema')
            db.execute('CREATE TABLE IF NOT EXISTS remote_offers ('
                       'run_key TEXT PRIMARY KEY REFERENCES native_worker_runs(key), node_id TEXT NOT NULL REFERENCES remote_nodes(node_id), '
                       'fingerprint TEXT NOT NULL, offer_json TEXT NOT NULL, status TEXT NOT NULL, '
                       'claim_id TEXT UNIQUE, epoch INTEGER NOT NULL, lease_expires_at REAL, '
                       'receipt_json TEXT, manifest_json TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS remote_claim_requests ('
                       'node_id TEXT NOT NULL REFERENCES remote_nodes(node_id), request_id TEXT NOT NULL, '
                       'response_json TEXT NOT NULL, PRIMARY KEY(node_id,request_id))')
            db.execute('CREATE TABLE IF NOT EXISTS remote_uploads ('
                       'claim_id TEXT NOT NULL REFERENCES remote_offers(claim_id), path TEXT NOT NULL, '
                       'sha256 TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY(claim_id,path))')
            sync_schema = db.execute("SELECT value FROM metadata WHERE key='remote_event_sync_schema'").fetchone()
            if sync_schema and sync_schema[0] != '1':
                raise ValueError('incompatible remote event sync schema')
            db.execute('CREATE TABLE IF NOT EXISTS remote_event_sync ('
                       'claim_id TEXT NOT NULL REFERENCES remote_offers(claim_id), epoch INTEGER NOT NULL CHECK(epoch>0), '
                       'seq INTEGER NOT NULL CHECK(seq>0), kind TEXT NOT NULL, raw_digest TEXT NOT NULL, data_json TEXT NOT NULL, '
                       'PRIMARY KEY(claim_id,epoch,seq))')
            db.execute("INSERT OR IGNORE INTO metadata VALUES('remote_event_sync_schema','1')")
            service_schema = db.execute("SELECT value FROM metadata WHERE key='remote_transport_service_schema'").fetchone()
            if service_schema and service_schema[0] != '1':
                raise ValueError('incompatible remote transport service schema')
            db.execute('CREATE TABLE IF NOT EXISTS remote_input_snapshots ('
                       'run_key TEXT PRIMARY KEY REFERENCES native_worker_runs(key), binding_json TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS remote_withdrawals ('
                       'run_key TEXT PRIMARY KEY REFERENCES remote_offers(run_key), reason_hash TEXT NOT NULL, reason TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS remote_transport_controls ('
                       'id TEXT PRIMARY KEY, run_key TEXT NOT NULL REFERENCES remote_offers(run_key), '
                       'control_json TEXT NOT NULL, status TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS remote_receipt_trees ('
                       'claim_id TEXT PRIMARY KEY REFERENCES remote_offers(claim_id), raw_digest TEXT NOT NULL, tree_json TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO metadata VALUES('remote_transport_service_schema','1')")
            db.execute("INSERT OR IGNORE INTO metadata VALUES('remote_claim_schema','1')")
            root = db.execute("SELECT value FROM metadata WHERE key='remote_artifact_root'").fetchone()
            if root and root[0] != str(self.artifact_root):
                raise IdempotencyConflictError('mission artifact root is already pinned')
            if not root:
                db.execute("INSERT INTO metadata VALUES('remote_artifact_root',?)", (str(self.artifact_root),))
                self._event(db, 'artifact_root', 'mission', {'artifact_root': str(self.artifact_root)})

    def _now(self) -> float:
        now = self.clock()
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
            raise ValueError('clock must return finite UTC Unix seconds')
        return float(now)

    def _event(self, db: Any, kind: str, key: str, data: dict[str, Any]) -> None:
        self.journal._event(db, 'node_' + kind, key, data | {'mission_id': self.registry.mission_id}, actor='controller')

    def _view(self, db: Any, row: Any) -> dict[str, Any]:
        return json.loads(row['offer_json']) | {
            'status': row['status'], 'claim_id': row['claim_id'], 'epoch': row['epoch'],
            'lease_expires_at': row['lease_expires_at'],
            'receipt': json.loads(row['receipt_json']) if row['receipt_json'] else None,
            'manifest': json.loads(row['manifest_json']) if row['manifest_json'] else None,
            'uploads': [dict(u) for u in db.execute(
                'SELECT path,sha256,size,status FROM remote_uploads WHERE claim_id=? ORDER BY path', (row['claim_id'],)).fetchall()]}

    def _run(self, db: Any, run_key: str) -> Any:
        row = db.execute('SELECT * FROM native_worker_runs WHERE key=?', (run_key,)).fetchone()
        if row is None or row['status'] != 'IN_FLIGHT' or row['receipt_json'] is not None:
            raise LeaseLost('remote offer requires a real IN_FLIGHT native reservation')
        self.journal._fence(db, row)
        return row

    def _sweep(self, db: Any, now: float) -> list[dict[str, Any]]:
        changed = []
        for row in db.execute("SELECT * FROM remote_offers WHERE status IN ('OFFERED','CLAIMED') ORDER BY rowid").fetchall():
            reason = None
            try:
                self.registry._active(db, row['node_id'])
                self._run(db, row['run_key'])
            except (PermissionError, LeaseLost):
                reason = 'node revoked or canonical reservation lost'
            if row['status'] == 'CLAIMED' and row['lease_expires_at'] <= now:
                reason = 'claim lease expired; execution remains unknown'
            if reason:
                db.execute("UPDATE remote_offers SET status='UNKNOWN' WHERE run_key=?", (row['run_key'],))
                self._event(db, 'claim_unknown', row['run_key'], {'claim_id': row['claim_id'], 'epoch': row['epoch'], 'reason': reason})
                changed.append(self._view(db, db.execute('SELECT * FROM remote_offers WHERE run_key=?', (row['run_key'],)).fetchone()))
        return changed

    def expire(self) -> list[dict[str, Any]]:
        with self.journal.store._transaction() as db:
            return self._sweep(db, self._now())

    def bind_input_snapshot(self, run_key: str, root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
        """Controller-only immutable binding; cached readback is not fresh admission."""
        run_key, root, manifest = _transport_key(run_key), _transport_root(root), _transport_manifest(manifest)
        _admit_transport_credentials({'run_key': run_key, 'root': str(root), 'manifest': manifest})
        with self.journal.store._transaction() as db:
            old = db.execute('SELECT binding_json FROM remote_input_snapshots WHERE run_key=?', (run_key,)).fetchone()
            if old:
                saved = json.loads(old[0])
                run = db.execute('SELECT fingerprint FROM native_worker_runs WHERE key=?', (run_key,)).fetchone()
                if (saved['root'] != str(root) or saved['manifest'] != manifest or run is None
                        or saved['reservation_fingerprint'] != run[0]):
                    raise IdempotencyConflictError('conflicting immutable input snapshot')
                return saved
            if db.execute('SELECT 1 FROM remote_offers WHERE run_key=?', (run_key,)).fetchone():
                raise IdempotencyConflictError('input snapshot is never backfilled into an existing offer')
            run = self._run(db, run_key)
            saved = {'mission_id': self.registry.mission_id, 'run_key': run_key, 'root': str(root),
                     'manifest': manifest, 'manifest_hash': digest(manifest), 'reservation_fingerprint': run['fingerprint']}
            if saved != redact(saved):
                raise ValueError('input binding contains credential material')
            _snapshot_read(root, manifest['files'])
            self._run(db, run_key)  # Snapshot IO must not cross the core lease.
            db.execute('INSERT INTO remote_input_snapshots VALUES(?,?)', (run_key, canonical_json(saved)))
            self._event(db, 'input_snapshot_bound', run_key, saved)
            return saved

    def _transport_view(self, db: Any, row: Any) -> dict[str, Any]:
        view = self._view(db, row)
        saved = db.execute('SELECT tree_json FROM remote_receipt_trees WHERE claim_id=?', (row['claim_id'],)).fetchone()
        return view | {'tree': json.loads(saved[0])} if saved else view

    def status(self, node_id: str, claim_id: str, epoch: int) -> dict[str, Any]:
        """Historical owner readback; gateway separately authenticates ACTIVE nodes."""
        with self.journal.store._transaction(immediate=False) as db:
            return self._transport_view(db, self._owned(db, node_id, claim_id, epoch, active=False))

    def read_input(self, node_id: str, claim_id: str, epoch: int, path: str) -> bytes:
        path = _path(path)
        with self.journal.store._transaction(immediate=False) as db:
            row = self._owned(db, node_id, claim_id, epoch)
            run_key = row['run_key']
            saved = db.execute('SELECT binding_json FROM remote_input_snapshots WHERE run_key=?', (run_key,)).fetchone()
            if saved is None:
                raise FileNotFoundError('claim has no fixed input snapshot')
            binding = json.loads(saved[0])
            manifest = _transport_manifest(binding['manifest'])
            offer = json.loads(row['offer_json'])
            if manifest != offer['input_manifest'] or binding['manifest_hash'] != offer['input_manifest_hash']:
                raise IdempotencyConflictError('input snapshot differs from immutable offer')
            if path not in {item['path'] for item in manifest['files']}:
                raise FileNotFoundError('input path is outside fixed snapshot manifest')
        # No DB read snapshot/lock spans IO. Revoke/core-owner writes during IO
        # must be visible in the NEW transaction below, not hidden by SQLite WAL.
        data = _snapshot_read(_transport_root(binding['root']), manifest['files'], path)
        with self.journal.store._transaction(immediate=False) as db:
            current = self._owned(db, node_id, claim_id, epoch)
            fixed = db.execute('SELECT binding_json FROM remote_input_snapshots WHERE run_key=?', (run_key,)).fetchone()
            if current['run_key'] != run_key or fixed is None or fixed[0] != saved[0]:
                raise IdempotencyConflictError('input identity changed during read')
            self._sync_fence(db, node_id, claim_id, epoch)
            if data is None:
                raise ValueError('fixed input bytes missing after verification')
            return data

    def withdraw(self, run_key: str, reason: str) -> dict[str, Any]:
        run_key = _transport_key(run_key)
        if not isinstance(reason, str) or not reason.strip() or len(reason.encode('utf-8')) > 2000:
            raise ValueError('withdraw requires nonempty text up to 2_000 UTF-8 bytes')
        fingerprint = digest(reason)
        with self.journal.store._transaction() as db:
            row = db.execute('SELECT * FROM remote_offers WHERE run_key=?', (run_key,)).fetchone()
            if row is None:
                raise FileNotFoundError('unknown remote offer')
            old = db.execute('SELECT reason_hash FROM remote_withdrawals WHERE run_key=?', (run_key,)).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise IdempotencyConflictError('conflicting immutable withdrawal')
                return self._transport_view(db, row)
            if row['status'] != 'OFFERED' or row['epoch'] != 0 or row['claim_id'] is not None:
                return self._transport_view(db, row)
            db.execute("UPDATE remote_offers SET status='WITHDRAWN' WHERE run_key=? AND status='OFFERED' AND epoch=0 AND claim_id IS NULL", (run_key,))
            db.execute('INSERT INTO remote_withdrawals VALUES(?,?,?)', (run_key, fingerprint, redact(reason)))
            self._event(db, 'withdrawn', run_key, {'status': 'WITHDRAWN', 'epoch': 0, 'claim_id': None,
                                                'reason': redact(reason), 'reason_hash': fingerprint})
            return self._transport_view(db, db.execute('SELECT * FROM remote_offers WHERE run_key=?', (run_key,)).fetchone())

    def post_controls(self, run_key: str, controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Internal controller-only interrupt queue; posting is not native delivery."""
        run_key, controls = _transport_key(run_key), _control_payload(controls)
        with self.journal.store._transaction(immediate=bool(controls)) as db:
            if db.execute('SELECT 1 FROM remote_offers WHERE run_key=?', (run_key,)).fetchone() is None:
                raise FileNotFoundError('unknown remote offer')
            fresh = []
            for item in controls:
                old = db.execute('SELECT * FROM remote_transport_controls WHERE id=?', (item['id'],)).fetchone()
                if old:
                    if old['run_key'] != run_key or json.loads(old['control_json']) != item:
                        raise IdempotencyConflictError('conflicting immutable transport control')
                else:
                    fresh.append(item)
            outstanding = db.execute("SELECT count(*) FROM remote_transport_controls WHERE run_key=? AND status='PENDING'", (run_key,)).fetchone()[0]
            if outstanding + len(fresh) > MAX_TRANSPORT_CONTROLS:
                raise ValueError('outstanding transport interrupts exceed bound')
            for item in fresh:
                db.execute("INSERT INTO remote_transport_controls VALUES(?,?,?,'PENDING')", (item['id'], run_key, canonical_json(item)))
            if fresh:
                self._event(db, 'controls_posted', run_key, {'controls': fresh})
            return [item | {'status': db.execute('SELECT status FROM remote_transport_controls WHERE id=?', (item['id'],)).fetchone()[0]}
                    for item in controls]

    def pending_controls(self, node_id: str, claim_id: str, epoch: int) -> list[dict[str, str]]:
        with self.journal.store._transaction(immediate=False) as db:
            row = self._owned(db, node_id, claim_id, epoch)
            result = [json.loads(r[0]) for r in db.execute(
                "SELECT control_json FROM remote_transport_controls WHERE run_key=? AND status='PENDING' ORDER BY rowid", (row['run_key'],))]
            self._sync_fence(db, node_id, claim_id, epoch)
            return result

    def _sync_fence(self, db: Any, node_id: str, claim_id: str, epoch: int,
                    original_deadline: float | None = None) -> tuple[Any, float]:
        row = self._owned(db, node_id, claim_id, epoch)
        now = self._now()
        if row['lease_expires_at'] <= now or original_deadline is not None and original_deadline <= now:
            raise LeaseLost('sync lost the original claim lease; do not redispatch')
        self._run(db, row['run_key'])  # Recheck canonical fence after sampling clock.
        return row, now

    def _sync_view(self, row: Any, last_seq: int) -> dict[str, Any]:
        return {'mission_id': self.registry.mission_id, 'run_key': row['run_key'], 'node_id': row['node_id'],
                'claim_id': row['claim_id'], 'epoch': row['epoch'], 'last_seq': last_seq,
                'lease_expires_at': row['lease_expires_at']}

    def sync(self, node_id: str, claim_id: str, epoch: int, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Atomic, fenced Codex event delivery; readbacks never renew execution."""
        batch = _sync_batch(events)  # Validate the entire batch before any callback/write.
        with self.journal.store._transaction(immediate=bool(batch)) as db:
            row, _ = self._sync_fence(db, node_id, claim_id, epoch)
            original_deadline = row['lease_expires_at']
            last_seq = db.execute('SELECT COALESCE(MAX(seq),0) FROM remote_event_sync WHERE claim_id=? AND epoch=?',
                                  (claim_id, epoch)).fetchone()[0]
            fresh = []
            for item in batch:
                if item['seq'] <= last_seq:
                    saved = db.execute('SELECT raw_digest FROM remote_event_sync WHERE claim_id=? AND epoch=? AND seq=?',
                                       (claim_id, epoch, item['seq'])).fetchone()
                    if saved is None:
                        raise ValueError('stored sync sequence has a gap')
                    if saved[0] != item['raw_digest']:
                        raise IdempotencyConflictError('conflicting immutable sync event')
                else:
                    if item['seq'] != last_seq + len(fresh) + 1:
                        raise ValueError('sync sequence gap after durable high-water mark')
                    fresh.append(item)
            if not fresh:
                row, _ = self._sync_fence(db, node_id, claim_id, epoch, original_deadline)
                return self._sync_view(row, last_seq)
            for item in fresh:
                self._sync_fence(db, node_id, claim_id, epoch, original_deadline)
                db.execute('INSERT INTO remote_event_sync VALUES(?,?,?,?,?,?)',
                           (claim_id, epoch, item['seq'], item['kind'], item['raw_digest'], item['data_json']))
                # Transport seq/digest are never injected into native acceptance data.
                self.journal.event_in(db, row['run_key'], item['kind'], json.loads(item['data_json']))
                if item['kind'] == 'control_ack':
                    data = json.loads(item['data_json'])
                    db.execute("UPDATE remote_transport_controls SET status=? WHERE id=? AND run_key=? AND status='PENDING'",
                               ('ACK' if data['accepted'] else 'REJECTED', data['command_id'], row['run_key']))
            row, now = self._sync_fence(db, node_id, claim_id, epoch, original_deadline)
            expiry = max(row['lease_expires_at'], now + self.lease_seconds)
            db.execute('UPDATE remote_offers SET lease_expires_at=? WHERE claim_id=? AND epoch=?', (expiry, claim_id, epoch))
            last_seq += len(fresh)
            self._event(db, 'events_synced', row['run_key'], {'claim_id': claim_id, 'epoch': epoch,
                        'first_seq': fresh[0]['seq'], 'last_seq': last_seq, 'lease_expires_at': expiry})
            # Check the ORIGINAL deadline even after renewal: time spent in hooks
            # or chain persistence never revives an already expired execution.
            row, _ = self._sync_fence(db, node_id, claim_id, epoch, original_deadline)
            return self._sync_view(row, last_seq)

    def offer(self, run_key: str, node_id: str, request: Request | dict[str, Any], input_manifest: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(run_key, str) or not run_key or len(run_key.encode()) > 200:
            raise ValueError('run_key must identify a canonical reservation')
        raw = asdict(request) if isinstance(request, Request) else dict(request) if isinstance(request, dict) else None
        if raw is None or set(raw) - ({f.name for f in fields(Request)} | {'driver'}):
            raise ValueError('offer requires native Request fields only')
        if raw.pop('driver', 'codex') != 'codex':
            raise ValueError('v1 driver is codex')
        try:
            native = Request(**raw)
        except (TypeError, AttributeError) as exc:
            raise ValueError('invalid native Request') from exc
        if native.model != 'gpt-6.1-sol' or native.mode != 'workspace-write' or native.session_id is not None:
            raise ValueError('v1 requires explicit gpt-6.1-sol workspace-write and a fresh session')
        raw = asdict(native)
        if raw != redact(raw):
            raise ValueError('offer contains credential material')
        if not isinstance(input_manifest, dict) or set(input_manifest) != {'files', 'output_paths'}:
            raise ValueError('input manifest requires files and output_paths only')
        files_ = _entries(input_manifest['files'])
        outputs = input_manifest['output_paths']
        if not isinstance(outputs, list) or len(outputs) > MAX_FILES:
            raise ValueError('output path count exceeds bound')
        outputs = [_path(p) for p in outputs]
        if len(set(outputs)) != len(outputs):
            raise ValueError('duplicate output path')
        _paths([f['path'] for f in files_] + outputs)
        manifest = {'files': files_, 'output_paths': sorted(outputs)}
        if len(canonical_json(manifest).encode()) > MAX_MANIFEST_BYTES:
            raise ValueError('input manifest exceeds bound')
        immutable = {'mission_id': self.registry.mission_id, 'run_key': run_key, 'node_id': node_id,
                     'task_id': native.task_id, 'driver': 'codex', 'request': raw,
                     'prompt_hash': digest(native.prompt), 'input_manifest': manifest, 'input_manifest_hash': digest(manifest)}
        if immutable != redact(immutable):
            raise ValueError('offer contains credential material')
        _admit_transport_credentials(immutable)
        fingerprint = digest(immutable)
        with self.journal.store._transaction() as db:
            old = db.execute('SELECT * FROM remote_offers WHERE run_key=?', (run_key,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise IdempotencyConflictError('conflicting immutable remote offer')
                return self._view(db, old)
            self.registry._active(db, node_id)
            run = self._run(db, run_key)
            if run['task_id'] != native.task_id:
                raise ValueError('Request task_id differs from reserved task')
            context_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lead_mission_contexts'").fetchone()
            if context_table:
                context = db.execute('SELECT binding_json FROM lead_mission_contexts WHERE run_key=?', (run_key,)).fetchone()
                if context and json.loads(context[0])['prompt_hash'] != digest(native.prompt):
                    raise IdempotencyConflictError('offer differs from frozen invocation prompt')
            role = db.execute('SELECT value FROM metadata WHERE key=?', ('techlead:roles:' + run_key,)).fetchone()
            if role:
                saved = json.loads(role[0])['data']
                if any(saved.get(k) != v for k, v in {'driver': 'codex', 'model': native.model, 'mode': native.mode, 'cwd': native.cwd}.items()):
                    raise IdempotencyConflictError('offer differs from frozen invocation role')
            snapshot = db.execute('SELECT binding_json FROM remote_input_snapshots WHERE run_key=?', (run_key,)).fetchone()
            input_root = Path(native.cwd)
            if snapshot:
                pinned = json.loads(snapshot[0])
                if pinned['manifest'] != manifest or pinned['reservation_fingerprint'] != run['fingerprint']:
                    raise IdempotencyConflictError('offer differs from fixed input snapshot')
                input_root = _transport_root(pinned['root'])
                _snapshot_read(input_root, files_)
            else:
                for item in files_:
                    _verify_file(Path(native.cwd), item)
            # Check existing output components as well; new output files are valid.
            root_fd = _directory(input_root)
            os.close(root_fd)
            for path in outputs:
                cursor = input_root
                for part in path.split('/'):
                    cursor = cursor / part
                    if cursor.is_symlink():
                        raise ValueError('output allowlist contains symlink')
            if snapshot:
                self.registry._active(db, node_id)
                self._run(db, run_key)
            saved = immutable | {'fingerprint': fingerprint, 'created_at': utc_now()}
            db.execute("INSERT INTO remote_offers VALUES(?,?,?,?,'OFFERED',NULL,0,NULL,NULL,NULL)",
                       (run_key, node_id, fingerprint, canonical_json(saved)))
            self._event(db, 'offered', run_key, {'node_id': node_id, 'fingerprint': fingerprint, 'prompt_hash': saved['prompt_hash'],
                                             'input_manifest_hash': saved['input_manifest_hash']})
            return self._view(db, db.execute('SELECT * FROM remote_offers WHERE run_key=?', (run_key,)).fetchone())

    def claim(self, node_id: str, request_id: str) -> dict[str, Any]:
        validate_request_id(request_id)
        self.expire()  # Persist fencing independently of a later rejected operation.
        with self.journal.store._transaction() as db:
            self.registry._active(db, node_id)
            old = db.execute('SELECT response_json FROM remote_claim_requests WHERE node_id=? AND request_id=?', (node_id, request_id)).fetchone()
            if old:
                return json.loads(old[0])
            pause = db.execute("SELECT value FROM metadata WHERE key='native_worker_paused'").fetchone()
            state = db.execute("SELECT value FROM metadata WHERE key='techlead:state'").fetchone()
            # Offers were reserved earlier; recheck shared uncertainty at the
            # actual claim boundary, without settling core or releasing offers.
            unresolved = bool(db.execute("SELECT 1 FROM native_worker_runs WHERE status='UNKNOWN' LIMIT 1").fetchone()
                              or db.execute("SELECT 1 FROM remote_offers WHERE status IN "
                                            "('UNKNOWN','RECONCILIATION_CANDIDATE') LIMIT 1").fetchone())
            blocked = bool(pause and pause[0] == '1' or state and json.loads(state[0]).get('stopped') or unresolved)
            row = None if blocked else db.execute("SELECT * FROM remote_offers WHERE node_id=? AND status='OFFERED' ORDER BY rowid LIMIT 1", (node_id,)).fetchone()
            result = {'mission_id': self.registry.mission_id, 'node_id': node_id, 'request_id': request_id,
                      'status': 'NO_WORK', 'claim': None}
            if row:
                self._run(db, row['run_key'])
                cid = 'claim_' + secrets.token_hex(16)
                db.execute("UPDATE remote_offers SET status='CLAIMED',claim_id=?,epoch=1,lease_expires_at=? WHERE run_key=?",
                           (cid, self._now() + self.lease_seconds, row['run_key']))
                current = db.execute('SELECT * FROM remote_offers WHERE run_key=?', (row['run_key'],)).fetchone()
                result.update(status='CLAIMED', claim=self._view(db, current))
            db.execute('INSERT INTO remote_claim_requests VALUES(?,?,?)', (node_id, request_id, canonical_json(result)))
            self._event(db, 'claimed' if row else 'claim_empty', row['run_key'] if row else node_id,
                        {'node_id': node_id, 'request_id': request_id, 'response_hash': digest(result)})
            return result

    def _owned(self, db: Any, node_id: str, claim_id: str, epoch: int, *, active: bool = True) -> Any:
        if not isinstance(node_id, str) or not isinstance(claim_id, str):
            raise ValueError('invalid node or claim identity')
        row = db.execute('SELECT * FROM remote_offers WHERE claim_id=?', (claim_id,)).fetchone()
        if row is None or row['node_id'] != node_id:
            raise PermissionError('claim does not belong to node')
        if type(epoch) is not int or epoch != row['epoch']:
            raise LeaseLost('claim epoch mismatch')
        if active:
            self.registry._active(db, node_id)
            if row['status'] != 'CLAIMED' or row['lease_expires_at'] <= self._now():
                raise LeaseLost('claim is no longer live; do not redispatch')
            self._run(db, row['run_key'])
        return row

    def heartbeat(self, node_id: str, claim_id: str, epoch: int) -> dict[str, Any]:
        self.expire()
        with self.journal.store._transaction() as db:
            row = self._owned(db, node_id, claim_id, epoch)
            deadline = max(row['lease_expires_at'], self._now() + self.lease_seconds)
            db.execute('UPDATE remote_offers SET lease_expires_at=? WHERE claim_id=?', (deadline, claim_id))
            self._event(db, 'heartbeat', row['run_key'], {'claim_id': claim_id, 'epoch': epoch, 'lease_expires_at': deadline})
            return self._view(db, db.execute('SELECT * FROM remote_offers WHERE claim_id=?', (claim_id,)).fetchone())

    def upload(self, node_id: str, claim_id: str, epoch: int, path: str, sha256: str, data: bytes) -> dict[str, Any]:
        path = _path(path)
        if type(data) is not bytes or len(data) > MAX_FILE_BYTES:
            raise ValueError('upload requires bounded bytes')
        if not isinstance(sha256, str) or not _HASH.fullmatch(sha256) or hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError('upload SHA256 mismatch')
        self.expire()
        # Persist intent FIRST, so a crash cannot silently overwrite a partial file.
        with self.journal.store._transaction() as db:
            row = self._owned(db, node_id, claim_id, epoch)
            if path not in json.loads(row['offer_json'])['input_manifest']['output_paths']:
                raise ValueError('upload path is outside fixed allowlist')
            old = db.execute('SELECT * FROM remote_uploads WHERE claim_id=? AND path=?', (claim_id, path)).fetchone()
            recovering = old is not None
            if old:
                if (old['sha256'], old['size']) != (sha256, len(data)):
                    raise IdempotencyConflictError('conflicting artifact upload')
            else:
                count, total = db.execute('SELECT count(*),COALESCE(sum(size),0) FROM remote_uploads WHERE claim_id=?', (claim_id,)).fetchone()
                if count >= MAX_FILES or total + len(data) > MAX_TOTAL_BYTES:
                    raise ValueError('upload count/total exceeds bound')
                db.execute("INSERT INTO remote_uploads VALUES(?,?,?,?,'PREPARING')", (claim_id, path, sha256, len(data)))
                self._event(db, 'upload_preparing', row['run_key'], {'claim_id': claim_id, 'epoch': epoch, 'path': path, 'sha256': sha256, 'size': len(data)})
        item = {'path': path, 'sha256': sha256, 'size': len(data)}
        with self.journal.store._transaction() as db:
            row = self._owned(db, node_id, claim_id, epoch)
            old = db.execute('SELECT * FROM remote_uploads WHERE claim_id=? AND path=?', (claim_id, path)).fetchone()
            root = self.artifact_root / claim_id
            parent, name = _parent(root, path, create=True)
            try:
                if old['status'] == 'STORED':
                    _verify_file(root, item)
                    return item | {'status': 'STORED'}
                try:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                except FileExistsError:
                    if not recovering:
                        raise IdempotencyConflictError('unrecognized retained artifact already exists')
                    _verify_file(root, item)  # Complete prior write only; partial files stay fenced.
                else:
                    try:
                        offset = 0
                        while offset < len(data):
                            written = os.write(fd, data[offset:])
                            if written <= 0:
                                raise OSError('artifact write made no progress')
                            offset += written
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    os.fsync(parent)
                    _verify_file(root, item)
            finally:
                os.close(parent)
            # Recheck lease after IO, before acknowledging durable transfer.
            self._owned(db, node_id, claim_id, epoch)
            db.execute("UPDATE remote_uploads SET status='STORED' WHERE claim_id=? AND path=?", (claim_id, path))
            self._event(db, 'uploaded', row['run_key'], item | {'claim_id': claim_id, 'epoch': epoch})
            return item | {'status': 'STORED'}

    def _receipt_late(self, db: Any, row: Any) -> bool:
        if row['status'] != 'CLAIMED' or row['lease_expires_at'] <= self._now():
            return True
        try:
            self.registry._active(db, row['node_id'])
            self._run(db, row['run_key'])
        except (PermissionError, LeaseLost):
            return True
        return False

    def receipt(self, node_id: str, claim_id: str, epoch: int, receipt: Receipt | dict[str, Any], manifest: list[dict[str, Any]],
                *, tree: Any = _NO_TREE) -> dict[str, Any]:
        safe = redact(_receipt_payload(receipt))
        entries = _entries(manifest)
        evidence = _tree_payload(tree) if tree is not _NO_TREE else None
        self.expire()
        with self.journal.store._transaction() as db:
            row = self._owned(db, node_id, claim_id, epoch, active=False)
            if row['receipt_json']:
                if json.loads(row['receipt_json']) != safe or json.loads(row['manifest_json']) != entries:
                    raise IdempotencyConflictError('conflicting terminal transport receipt')
                if evidence is not None:
                    saved = db.execute('SELECT raw_digest FROM remote_receipt_trees WHERE claim_id=?', (claim_id,)).fetchone()
                    if saved is None or saved[0] != evidence[0]:
                        raise IdempotencyConflictError('conflicting immutable terminal tree; no historical backfill')
                return self._transport_view(db, row) if evidence is not None else self._view(db, row)
            # A late result must survive an interrupted upload; evaluate fencing
            # BEFORE demanding a complete manifest. Never materialize PREPARING.
            late = self._receipt_late(db, row)
            uploads = db.execute('SELECT * FROM remote_uploads WHERE claim_id=? ORDER BY path', (claim_id,)).fetchall()
            stored = [u for u in uploads if u['status'] == 'STORED']
            incomplete_paths = [u['path'] for u in uploads if u['status'] != 'STORED']
            if (not late and incomplete_paths) or entries != [
                {'path': u['path'], 'sha256': u['sha256'], 'size': u['size']} for u in stored]:
                raise ValueError('receipt manifest differs from complete retained uploads')
            for item in entries:
                _verify_file(self.artifact_root / claim_id, item)
            # Verification IO may cross a lease boundary too. Preserve that
            # result as a candidate rather than acknowledging a live receipt.
            late = late or self._receipt_late(db, row)
            status = 'RECONCILIATION_CANDIDATE' if late else 'UNKNOWN' if safe['status'] == 'UNKNOWN' else 'RECEIPTED'
            db.execute('UPDATE remote_offers SET status=?,receipt_json=?,manifest_json=? WHERE claim_id=?',
                       (status, canonical_json(safe), canonical_json(entries), claim_id))
            tree_event = {}
            if evidence is not None:
                db.execute('INSERT INTO remote_receipt_trees VALUES(?,?,?)', (claim_id, evidence[0], evidence[1]))
                reported = json.loads(evidence[1])
                tree_event = {'tree_hash': evidence[0], 'tree_reported_complete': reported['complete'],
                              'tree_reported_error_count': len(reported['errors'])}
            self._event(db, 'receipt', row['run_key'], {'claim_id': claim_id, 'epoch': epoch, 'status': status,
                                                     'receipt_hash': digest(safe), 'manifest_hash': digest(entries),
                                                     'incomplete_paths': incomplete_paths} | tree_event)
            current = db.execute('SELECT * FROM remote_offers WHERE claim_id=?', (claim_id,)).fetchone()
            return self._transport_view(db, current) if evidence is not None else self._view(db, current)

    def get(self, run_key: str) -> dict[str, Any] | None:
        if not isinstance(run_key, str):
            raise ValueError('run_key must be text')
        with self.journal.store._transaction(immediate=False) as db:
            row = db.execute('SELECT * FROM remote_offers WHERE run_key=?', (run_key,)).fetchone()
            return self._view(db, row) if row else None
