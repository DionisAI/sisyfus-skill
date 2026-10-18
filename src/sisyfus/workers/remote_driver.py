"""Standalone controller adapter for an ALREADY reserved remote Codex worker.

This module neither reserves nor completes canonical work, renews leases, starts
native processes, nor approves evidence. NodeClaims owns transport commits;
remote_artifacts owns retained IO. Lead wiring and acceptance remain separate.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Callable

from . import remote_artifacts as artifacts
from .node_claims import _entries, _receipt_payload
from .protocol import ControlSource, EventSink, Receipt, Request, digest

_NODE = re.compile(r'node_[0-9a-f]{32}\Z')
_CLAIM = re.compile(r'claim_[0-9a-f]{32}\Z')
_CONTROL = re.compile(r'[A-Za-z0-9_.:-]{1,200}\Z')
_IMMUTABLE = ('mission_id', 'run_key', 'node_id', 'task_id', 'driver', 'request',
              'prompt_hash', 'input_manifest', 'input_manifest_hash')
_RUN = ('key', 'task_id', 'fingerprint', 'continuation_id', 'lease_token')
_STATES = {'OFFERED', 'CLAIMED', 'WITHDRAWN', 'UNKNOWN', 'RECEIPTED', 'RECONCILIATION_CANDIDATE'}


def _finite(value: Any, name: str) -> float:
    """Accept finite actual numbers only, never bool/string coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' requires a finite numeric value')
    return float(value)


class RemoteCodexDriver:
    """One controller-owned run, fixed roots/identity and unchanged Request→Receipt.

Only interrupts are relayed. Runtime heartbeat remains the existing caller's
responsibility. materialization is an independent candidate/before/delta or
explicit diagnostics, never a verifier verdict or permission to retry.
    """
    name = 'codex'
    controls = ('interrupt',)

    def __init__(self, claims: Any, run_key: str, node_id: str, *,
                 input_snapshot: str | Path, candidate_root: str | Path,
                 output_paths: list[str], poll_seconds: float = 0.2,
                 clock: Callable[[], float] = time.monotonic):
        """Pin controller parameters without creating roots or mutating the journal."""
        if not isinstance(run_key, str) or not run_key.strip() or len(run_key.encode('utf-8')) > 200:
            raise ValueError('run_key must identify the controller reservation')
        if not isinstance(node_id, str) or not _NODE.fullmatch(node_id):
            raise ValueError('node_id must identify the fixed node')
        if not callable(clock):
            raise ValueError('clock must be callable')
        self.claims, self.run_key, self.node_id = claims, run_key, node_id
        self.input_snapshot, self.candidate_root = artifacts._root(input_snapshot), artifacts._root(candidate_root)
        self.output_paths = tuple(artifacts._input_manifest({'files': [], 'output_paths': output_paths})['output_paths'])
        self.poll_seconds = _finite(poll_seconds, 'poll_seconds')
        if self.poll_seconds <= 0:
            raise ValueError('poll_seconds must be positive')
        self.clock, self._last_clock = clock, None
        self._sample()
        self._mission_id = claims.registry.mission_id
        self._canonical = self._metadata = self._offer_identity = self._owner = None
        self._binding = None
        self._binding_pinned = self._used = self._historical = self._offering = False
        self._control_ids: dict[str, str] = {}
        self.materialization: dict[str, Any] | None = None

    def _sample(self) -> float:
        """Bound one invocation by a finite, nondecreasing controller clock."""
        now = _finite(self.clock(), 'clock')
        if self._last_clock is not None and now < self._last_clock:
            raise ValueError('clock moved backwards')
        self._last_clock = now
        return now

    def _core(self, request: Request) -> None:
        """Read-only current same-token fence; pin canonical and frozen metadata."""
        with self.claims.journal.store._transaction(immediate=False) as db:
            row = db.execute('SELECT * FROM native_worker_runs WHERE key=?', (self.run_key,)).fetchone()
            if (row is None or row['status'] != 'IN_FLIGHT' or row['receipt_json'] is not None
                    or row['task_id'] != request.task_id or not row['continuation_id'] or not row['lease_token']):
                raise ValueError('matching leased IN_FLIGHT reservation required')
            self.claims.journal._fence(db, row)
            canonical = tuple(row[k] for k in _RUN)
            if self._canonical is not None and canonical != self._canonical:
                raise ValueError('canonical reservation identity changed')
            mission = db.execute("SELECT value FROM metadata WHERE key='remote_node_mission_id'").fetchone()
            if mission is None or mission[0] != self._mission_id or self.claims.registry.mission_id != self._mission_id:
                raise ValueError('mission namespace changed')
            role = db.execute('SELECT value FROM metadata WHERE key=?', ('techlead:roles:' + self.run_key,)).fetchone()
            context = None
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lead_mission_contexts'").fetchone():
                context = db.execute('SELECT binding_json FROM lead_mission_contexts WHERE run_key=?', (self.run_key,)).fetchone()
            metadata = (role[0] if role else None, context[0] if context else None)
            if self._metadata is not None and metadata != self._metadata:
                raise ValueError('frozen role/context metadata changed')
            if role:
                saved = json.loads(role[0])
                data = saved['data']
                expected = {'driver': 'codex', 'model': request.model, 'mode': request.mode, 'cwd': request.cwd}
                if (saved.get('key', self.run_key) != self.run_key or any(data.get(k) != v for k, v in expected.items())
                        or data.get('role', 'worker') != 'worker'
                        or data.get('node', request.task_id) != request.task_id
                        or data.get('task_id', request.task_id) != request.task_id):
                    raise ValueError('Request differs from frozen worker role')
            if context:
                data = json.loads(context[0])
                if (data['prompt_hash'] != digest(request.prompt) or data.get('role', 'worker') != 'worker'
                        or data.get('task_id', request.task_id) != request.task_id
                        or data.get('prompt', request.prompt) != request.prompt):
                    raise ValueError('Request differs from frozen worker context')
            self._canonical, self._metadata = canonical, metadata

    def _check_binding(self, manifest: dict[str, Any], *, required: bool) -> None:
        """Check the immutable controller snapshot binding, not mutable Request.cwd."""
        with self.claims.journal.store._transaction(immediate=False) as db:
            row = db.execute('SELECT binding_json FROM remote_input_snapshots WHERE run_key=?', (self.run_key,)).fetchone()
            raw = row[0] if row else None
        if self._binding_pinned and raw != self._binding:
            raise ValueError('fixed input snapshot binding changed')
        if row:
            data = json.loads(raw)
            expected = {'mission_id': self._mission_id, 'run_key': self.run_key, 'root': str(self.input_snapshot),
                        'manifest': manifest, 'manifest_hash': digest(manifest),
                        'reservation_fingerprint': self._canonical[2]}
            if data != expected:
                raise ValueError('input snapshot belongs to a different invocation')
        elif required:
            raise ValueError('fixed input snapshot binding missing')
        self._binding, self._binding_pinned = raw, True

    def _roots(self, request: Request) -> None:
        """Check actual disjoint identities and existing parents BEFORE snapshot IO."""
        source, uploads = artifacts._root(request.cwd), artifacts._root(self.claims.artifact_root)
        roots = (source, uploads, self.input_snapshot, self.candidate_root)
        for target in roots[2:]:
            identifier, _, missing = artifacts._root_boundary(target)
            if identifier is not None:
                raise FileExistsError('exclusive destination already exists')
            if missing != 1:
                raise ValueError('destination requires an already prepared parent')
        for i, first in enumerate(roots):
            for second in roots[i + 1:]:
                if artifacts._overlap(first, second):
                    raise ValueError('root_overlap')
        # Two nonexistent leaves have no inode yet. Compare their actual parent
        # identities plus case-folded leaf names without creating either leaf.
        first, second = self.input_snapshot, self.candidate_root
        if (artifacts._root_boundary(first.parent)[0] == artifacts._root_boundary(second.parent)[0]
                and first.name.casefold() == second.name.casefold()):
            raise ValueError('root_overlap')

    def _view(self, view: Any, request: Request) -> dict[str, Any]:
        """Verify exact immutable offer/hash and monotone claimed ownership identity."""
        if not isinstance(view, dict):
            raise ValueError('remote offer missing')
        immutable = {k: view[k] for k in _IMMUTABLE}
        manifest = artifacts._input_manifest(view['input_manifest'])
        if (view['mission_id'] != self._mission_id or view['run_key'] != self.run_key
                or view['node_id'] != self.node_id or view['task_id'] != request.task_id or view['driver'] != 'codex'
                or view['request'] != asdict(request) or view['prompt_hash'] != digest(request.prompt)
                or manifest != view['input_manifest'] or tuple(manifest['output_paths']) != self.output_paths
                or view['input_manifest_hash'] != digest(manifest) or view['fingerprint'] != digest(immutable)):
            raise ValueError('remote offer identity/hash mismatch')
        fixed = digest(immutable | {'fingerprint': view['fingerprint'], 'created_at': view['created_at']})
        if self._offer_identity is not None and fixed != self._offer_identity:
            raise ValueError('immutable remote offer changed')
        status, epoch, claim = view['status'], view['epoch'], view['claim_id']
        if status not in _STATES or type(epoch) is not int:
            raise ValueError('invalid transport status/epoch')
        if claim is None:
            if epoch != 0 or status not in {'OFFERED', 'WITHDRAWN', 'UNKNOWN'} or self._owner is not None:
                raise ValueError('unclaimed identity differs from transport state')
        else:
            if not isinstance(claim, str) or not _CLAIM.fullmatch(claim) or epoch != 1 or status in {'OFFERED', 'WITHDRAWN'}:
                raise ValueError('claimed identity differs from transport state')
            _finite(view['lease_expires_at'], 'node lease deadline')
            owner = (claim, epoch, view['node_id'])
            if self._owner is not None and owner != self._owner:
                raise ValueError('remote claim ownership changed')
            self._owner = owner
        self._offer_identity = fixed
        self._check_binding(manifest, required=not self._historical)
        return view

    def _read(self, request: Request) -> dict[str, Any]:
        """Use public owner status for full tree; readback never renews either lease."""
        self._core(request)
        basic = self._view(self.claims.get(self.run_key), request)
        current = basic
        if basic['claim_id'] is not None:
            current = self._view(self.claims.status(self.node_id, basic['claim_id'], basic['epoch']), request)
            if basic['status'] in {'RECEIPTED', 'UNKNOWN', 'RECONCILIATION_CANDIDATE'}:
                if any(current.get(k) != v for k, v in basic.items()):
                    raise ValueError('terminal transport facts changed during readback')
        self._core(request)
        return current

    def _terminal_guard(self, request: Request, expected: dict[str, Any]) -> None:
        """Require the exact durable terminal/receipt/tree/owner and current core fence."""
        current = self._read(request)
        if current['status'] != 'RECEIPTED' or digest(current) != digest(expected):
            raise ValueError('terminal receipt currency changed')

    def _waiting(self, request: Request) -> dict[str, Any]:
        """Re-read immediately before relay/wait; historical status is not a lease.

NodeClaims.expire persists loss without renewal. A deadline can cross during
status/controls, so explicitly check it after readback as well. Timely terminal
receipts use the separate terminal guard and need no active node deadline.
        """
        self.claims.expire()
        view = self._read(request)
        if view['status'] == 'CLAIMED':
            now = _finite(self.claims.clock(), 'node clock')
            active = any(n['node_id'] == self.node_id and n['status'] == 'ACTIVE'
                         for n in self.claims.registry.inventory())
            if now < 0 or view['lease_expires_at'] <= now or not active:
                self.claims.expire()
                raise ValueError('node lease/identity lost before wait or interrupt relay')
            self._core(request)
        return view

    def _generated(self, status: str, code: str, request: Request,
                   exception: Exception | None = None) -> Receipt:
        """Expose content-free explicit transport errors and retain prior IO diagnostics."""
        error = {'code': code}
        if exception is not None:
            error['exception_type'] = type(exception).__name__
        if status == 'UNKNOWN':
            previous = self.materialization
            self.materialization = {'status': 'UNKNOWN', 'error': error}
            if previous is not None:
                self.materialization['retained'] = previous
        elif exception is not None and isinstance(exception, artifacts.ArtifactError):
            self.materialization = {'status': 'INVALID', 'report': exception.report}
        return Receipt(status, error='remote_driver:' + code +
                       (' (' + type(exception).__name__ + ')' if exception is not None else ''),
                       requested_model=request.model, actual_model=None)

    def _finish(self, receipt: Receipt, request: Request, *,
                expected: dict[str, Any] | None = None, absent: bool = False) -> Receipt:
        """Fence every return; known nonexecution requires an exact persisted/absent proof."""
        try:
            self._core(request)
            if expected is not None and digest(self._read(request)) != digest(expected):
                raise ValueError('offer changed before return')
            if absent and self.claims.get(self.run_key) is not None:
                raise ValueError('offer exists despite preparation failure')
            self._core(request)
        except Exception as exc:
            return self._generated('UNKNOWN', 'return_fence', request, exc)
        return receipt

    def _commands(self, source: ControlSource, emit: EventSink) -> list[dict[str, str]]:
        """Bound controller controls, reject unsupported data, never invent native ACK."""
        rows = source()
        if not isinstance(rows, list) or len(rows) > 100 or len(json.dumps(rows, allow_nan=False).encode()) > 32_000:
            raise ValueError('controller controls exceed the fixed batch boundary')
        interrupts = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('control must have an identity')
            identity = row.get('id')
            if not isinstance(identity, str) or not _CONTROL.fullmatch(identity):
                raise ValueError('invalid controller control identity')
            payload = {k: row.get(k) for k in ('id', 'action', 'text')}
            fingerprint = digest(payload)
            old = self._control_ids.get(identity)
            if old is not None and old != fingerprint:
                raise ValueError('control identity reused with changed data')
            invalid = (set(row) - {'id', 'action', 'text', 'run_key', 'status', 'created_at'}
                       or row.get('run_key', self.run_key) != self.run_key
                       or not {'id', 'action', 'text'} <= set(row))
            supported = not invalid and payload['action'] == 'interrupt' and payload['text'] == ''
            if supported:
                interrupts.append(payload)
            elif old is None:
                emit('control_ack', {'command_id': identity, 'accepted': False,
                    'error': {'code': 'UNSUPPORTED_CONTROL' if payload['action'] != 'interrupt' else 'INVALID_CONTROL',
                              'message': 'RemoteCodexDriver v1 supports fixed interrupt controls only'}})
            self._control_ids[identity] = fingerprint
        return interrupts

    def _materialize(self, request: Request, view: dict[str, Any]) -> Receipt:
        """Keep known native status; independently validate COMPLETE tree/delta/bytes."""
        native = Receipt(**_receipt_payload(view['receipt']))
        if native.status == 'UNKNOWN':
            raise ValueError('RECEIPTED lacks a known native terminal')
        self._terminal_guard(request, view)
        manifest, tree, uploads = view['input_manifest'], view.get('tree'), view['uploads']
        derivation_error = False
        try:
            regular = _entries(tree['files'])
            deleted = sorted({f['path'] for f in manifest['files']} - {f['path'] for f in regular})
        except (KeyError, TypeError, ValueError, UnicodeError):
            deleted, derivation_error = [], True
        delta = artifacts.exact_delta(manifest, tree, uploads, deleted)
        if derivation_error:
            delta['errors'].append({'code': 'deletion_derivation', 'path': ''})
            delta['valid'] = False
        self._terminal_guard(request, view)  # Pure calculation may race a state change too.
        if not delta['valid']:
            self.materialization = {'status': 'INVALID', 'report': delta}
        else:
            result = None
            try:
                self._terminal_guard(request, view)
                result = artifacts.materialize_candidate(self.input_snapshot, manifest, tree, uploads, deleted,
                    artifact_root=self.claims.artifact_root, claim_id=view['claim_id'], candidate_root=self.candidate_root)
            except Exception as exc:
                report = exc.report if isinstance(exc, artifacts.ArtifactError) else {
                    'valid': False, 'errors': [{'code': 'materialization_io', 'path': ''}],
                    'exception_type': type(exc).__name__}
                self.materialization = {'status': 'INVALID', 'report': report}
            try:
                self._terminal_guard(request, view)
            except Exception:
                if result is not None:
                    self.materialization = {'status': 'UNKNOWN', 'retained': result}
                raise
            if result is not None:
                if (set(result) != {'candidate', 'before', 'delta'} or not result['delta']['valid']
                        or result['candidate'] != str(self.candidate_root / 'candidate')
                        or result['before'] != str(self.candidate_root / 'before')):
                    raise ValueError('materialization returned a different controller envelope')
                self.materialization = result
        return self._finish(native, request, expected=view)

    def run(self, request: Request, emit: EventSink, controls: ControlSource = lambda: []) -> Receipt:
        """Prepare/bind/offer once, wait with current fences, return native or UNKNOWN.

Old offers are read-only. Withdrawn epoch-zero/no-claim or proven absent offers
alone yield known transport ERROR. Native terminal with invalid artifacts stays
terminal with INVALID diagnostics. No native events already synced by N1 emit.
        """
        if self._used:
            raise RuntimeError('RemoteCodexDriver instances run once')
        self._used = True
        if not isinstance(request, Request):
            raise ValueError('run requires the unchanged native Request')
        try:
            start = self._sample()
            self._core(request)
            if request.model != 'gpt-6.1-sol' or request.mode != 'workspace-write' or request.session_id is not None:
                raise ValueError('v1 requires a fresh explicit Sol workspace-write worker')
            prior = self.claims.get(self.run_key)
            if prior is not None:
                self._historical = True
                view = self._read(request)
                if view['status'] == 'RECEIPTED':
                    native = Receipt(**_receipt_payload(view['receipt']))
                    if native.status == 'UNKNOWN':
                        raise ValueError('historical RECEIPTED is not a known terminal')
                    self.materialization = {'status': 'NOT_MATERIALIZED', 'reason': 'historical offer is read-only'}
                    return self._finish(native, request, expected=view)
                status = 'ERROR' if view['status'] == 'WITHDRAWN' and view['epoch'] == 0 and view['claim_id'] is None else 'UNKNOWN'
                return self._finish(self._generated(status, 'historical_offer', request), request, expected=view)
            for method in ('bind_input_snapshot', 'status', 'withdraw', 'post_controls', 'expire'):
                if not callable(getattr(self.claims, method, None)):
                    raise ValueError('required NodeClaims transport method missing: ' + method)
            deadline = start + request.timeout
            self._roots(request)
            manifest = artifacts.create_input_snapshot(request.cwd, self.input_snapshot, list(self.output_paths))
            self._core(request)
            if self._sample() >= deadline:
                return self._finish(self._generated('ERROR', 'preparation_timeout', request), request, absent=True)
            self.claims.bind_input_snapshot(self.run_key, self.input_snapshot, manifest)
            self._check_binding(manifest, required=True)
            self._core(request)
            if self._sample() >= deadline:
                return self._finish(self._generated('ERROR', 'preparation_timeout', request), request, absent=True)
            self._offering = True  # An exception beyond this boundary has unknown commit.
            view = self._view(self.claims.offer(self.run_key, self.node_id, request, manifest), request)
            while True:
                if view['status'] in {'OFFERED', 'CLAIMED'}:
                    self.claims.expire()  # Persist loss; never requeue or renew.
                view = self._read(request)
                if view['status'] == 'RECEIPTED':
                    return self._materialize(request, view)
                if view['status'] in {'UNKNOWN', 'RECONCILIATION_CANDIDATE'}:
                    return self._finish(self._generated('UNKNOWN', 'transport_unknown', request), request, expected=view)
                if view['status'] == 'WITHDRAWN':
                    return self._finish(self._generated('ERROR', 'withdrawn_unclaimed', request), request, expected=view)
                interrupts = self._commands(controls, emit)
                self._core(request)
                now = self._sample()
                timed_out = now >= deadline
                if timed_out or interrupts and view['status'] == 'OFFERED':
                    reason = 'single invocation deadline' if timed_out else 'operator interrupt before claim'
                    view = self._view(self.claims.withdraw(self.run_key, reason), request)
                    if view['status'] == 'WITHDRAWN' and view['epoch'] == 0 and view['claim_id'] is None:
                        return self._finish(self._generated('ERROR', 'withdrawn_unclaimed', request), request, expected=view)
                    if timed_out:
                        return self._finish(self._generated('UNKNOWN', 'deadline_after_claim_or_unknown', request), request)
                    view = self._read(request)
                if interrupts and view['status'] == 'CLAIMED':
                    # Both leases are active here; status alone is never permission.
                    view = self._waiting(request)
                    if view['status'] != 'CLAIMED':
                        continue
                    self._core(request)
                    self.claims.post_controls(self.run_key, interrupts)
                    self._core(request)
                # Clock callbacks may change currency; sample before the final
                # wait guard so no callback sits between that fence and sleep.
                remaining = deadline - self._sample()
                view = self._waiting(request)
                if view['status'] not in {'OFFERED', 'CLAIMED'}:
                    continue
                if remaining > 0:
                    time.sleep(min(self.poll_seconds, remaining))
        except Exception as exc:
            status = 'UNKNOWN' if self._offering or self._historical else 'ERROR'
            receipt = self._generated(status, 'transport_failure' if status == 'UNKNOWN' else 'preparation_failure', request, exc)
            return self._finish(receipt, request, absent=status == 'ERROR')
