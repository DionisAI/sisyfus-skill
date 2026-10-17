"""Independent stable-accounting close admission; original observed4 immutable.

Real Hub/core stores; exactly one dynamic wall-counter leaf is separated from
stable equality, with raw snapshots and accounting samples retained unchanged.
Process Thread DI never executes targets. Targeted source-line barrier DI pauses
after the actual session lookup has returned, before final admission.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

from sisyfus.workers import lead_console
from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.protocol import digest, redact
from test_lead_mission import make_spec


def _save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def _stable_core(raw):
    result = copy.deepcopy(raw)
    wall = result['counters'].pop('wall_minutes')  # Exactly this one leaf, no other filters.
    assert type(wall) in (int, float) and math.isfinite(wall) and wall >= 0
    return result


def _stable_readback(raw):
    result = copy.deepcopy(raw)
    result['core_snapshot'] = _stable_core(result['core_snapshot'])
    return result


class _Fixture:
    def __init__(self, root, monkeypatch):
        self.root, self.trace, self.wall_samples = root, [], []
        self.close_returned = False
        self.hub = MissionHub(root / 'hub')
        inputs = root / 'fixed-input'
        inputs.mkdir()
        self.ident = self.hub.create(make_spec(inputs))['id']
        self.session = self.hub._session(self.ident)
        self.mission = self.session.mission
        assert type(self.mission) is LeadMission and self.session.thread is None
        wrapped = self.hub.snapshot(self.ident)
        assert set(wrapped) == {'id', 'snapshot', 'controller', 'controls'}
        self.sample_wall('calibration.Hub.snapshot', wrapped['snapshot'])
        elapsed_start = time.monotonic()
        time.sleep(.01)  # Real elapsed accounting; no clock freeze/replacement.
        direct = self.mission.snapshot()
        self.sample_wall('calibration.LeadMission.snapshot', direct)
        elapsed = time.monotonic() - elapsed_start
        _save(root / 'raw-wrapper-direct-calibration.json', {
            'Hub_raw': wrapped, 'core_raw': direct, 'real_elapsed_monotonic_seconds': elapsed,
            'only_separated_core_leaf': 'counters.wall_minutes', 'samples': self.wall_samples[:]})
        assert elapsed > 0 and _stable_core(wrapped['snapshot']) == _stable_core(direct)
        assert wrapped['controls'] == [] and direct['stopped'] is False
        assert 'placement_preparation' not in direct and self.mission.journal.runs() == []
        self.before = self.readback('before.close')
        _save(root / 'raw-input-readback.json', self.before)
        with (root / 'before-autonomy.sqlite3.bytes').open('xb') as stream:
            stream.write(Path(self.mission.store.path).read_bytes())
        owner = self

        class ProcessThreadDI:
            def __init__(self, group=None, target=None, name=None, args=(), kwargs=None,
                         *, daemon=None, context=None):
                assert group is None and callable(target)
                owner.note('process.construct', name=name, target_name=target.__name__)

            def start(self):
                owner.note('process.start_attempt')  # Native target never executes.

            def is_alive(self):
                return False

            def join(self, timeout=None):
                owner.note('process.join', timeout=timeout)

        proxy = SimpleNamespace(**vars(threading))
        proxy.Thread = ProcessThreadDI
        monkeypatch.setattr(lead_console, 'threading', proxy)

    def note(self, kind, **fields):
        self.trace.append({'order': len(self.trace), 'kind': kind,
            'after_close_return': self.close_returned, 'monotonic': time.monotonic(), **fields})

    def sample_wall(self, label, raw):
        wall = raw['counters']['wall_minutes']
        assert type(wall) in (int, float) and math.isfinite(wall) and wall >= 0
        sample = {'label': label, 'wall_minutes': wall, 'observed_monotonic': time.monotonic()}
        if self.wall_samples:
            previous = self.wall_samples[-1]
            assert wall >= previous['wall_minutes'], 'actual wall accounting must be monotonic'
            assert sample['observed_monotonic'] >= previous['observed_monotonic']
        self.wall_samples.append(sample)

    def readback(self, label):
        path = Path(self.mission.store.path)
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
        try:
            dump = '\n'.join(db.iterdump())
        finally:
            db.close()
        raw = self.mission.snapshot()
        self.sample_wall(label, raw)
        source = Path(self.mission.spec['source'])
        source_files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(source.rglob('*')) if p.is_file()}
        events = self.mission.journal.events(0, limit=1000)
        assert len(events) < 1000, 'fixture hash-chain projection must be complete'
        return {'core_snapshot': raw, 'controls': self.hub.controls(self.ident),
                'events': events, 'runs': self.mission.journal.runs(),
                'raw_state': self.mission.journal.state(), 'spec': copy.deepcopy(self.mission.spec),
                'spec_hash': digest(self.mission.spec), 'source_files': source_files,
                'SQL_dump': dump, 'SQL_sha256': hashlib.sha256(dump.encode()).hexdigest(),
                'main_bytes_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'stop_event': self.mission.stop.is_set()}

    def close(self):
        assert self.session.thread is None
        self.note('close.enter_idle')
        self.hub.close()
        self.close_returned = True
        self.note('close.return_idle')
        after = self.readback('after.idle.close')
        _save(self.root / 'raw-after-idle-close.json', after)
        assert _stable_readback(after) == _stable_readback(self.before)
        assert after['stop_event'] is False and after['core_snapshot']['stopped'] is False

    def call(self, action, *, barrier=None):
        calls, response, error = [], None, None
        observed = {MissionHub._record.__code__: 'Hub._record', MissionHub._ack.__code__: 'Hub._ack',
            LeadMission._request_placement_preparation.__code__: 'LeadMission._request_placement_preparation',
            LeadMission._save_placement_preparation.__code__: 'LeadMission._save_placement_preparation',
            LeadMission.run.__code__: 'LeadMission.run',
            LeadMission.prepare_for_placement.__code__: 'LeadMission.prepare_for_placement'}
        target_code = MissionHub.control.__code__ if action == 'start' else MissionHub.prepare_placement.__code__

        def profile(frame, event, arg):
            if event == 'call' and frame.f_code in observed:
                calls.append(observed[frame.f_code])

        def delayed_after_lookup(frame, event, arg):
            if frame.f_code is not target_code:
                return None
            if (event == 'line' and not barrier['retrieved'].is_set()
                    and frame.f_locals.get('session') is self.session):
                # The real _session has returned into the actual caller local.
                # No replacement session, frame retention or global stack scan.
                assert self.session.thread is None
                self.note('caller.real_lookup_returned_before_admission', source_line=frame.f_lineno)
                barrier['retrieved'].set()
                if not barrier['release'].wait(3):
                    raise AssertionError('post-lookup barrier release bound')
                assert self.close_returned
                self.note('caller.continues_only_after_completed_close')
            return delayed_after_lookup

        previous_profile, previous_trace = sys.getprofile(), sys.gettrace()
        self.note('caller.public_enter', action=action)
        sys.setprofile(profile)
        if barrier is not None:
            sys.settrace(delayed_after_lookup)
        try:
            if action == 'start':
                response = self.hub.start(self.ident, allow_local_workers=True, max_cycles=1)
            else:
                response = self.hub.prepare_placement(self.ident,
                    'fixture_host_stable_prepare_0001', allow_planning=True)
        except BaseException as exc:
            error = exc
        finally:
            sys.settrace(previous_trace)
            sys.setprofile(previous_profile)
        self.note('caller.public_return', action=action, error_type=None if error is None else type(error).__name__)
        return response, error, calls

    def assert_fenced(self, action, result):
        response, error, calls = result
        after = self.readback('after.public.call')
        _save(self.root / 'raw-after-public-call.json', after)
        with (self.root / 'after-autonomy.sqlite3.bytes').open('xb') as stream:
            stream.write(Path(self.mission.store.path).read_bytes())
        rejected = (isinstance(error, (RuntimeError, PermissionError)) and
                    any(word in str(error).lower() for word in ('close', 'closing')))
        checks = {'explicit_closed_rejection': rejected, 'no_response': response is None,
            'zero_control_preparation_or_native_method_entries': calls == [],
            'zero_process_construct_start_join': not any(t['kind'].startswith('process.') for t in self.trace),
            'exact_stable_core_SQL_state_events_controls_runs_spec_source_mainbytes':
                _stable_readback(after) == _stable_readback(self.before),
            'idle_no_durable_Stop_mask': after['stop_event'] is False and after['core_snapshot']['stopped'] is False,
            'zero_native_reservations': after['runs'] == []}
        _save(self.root / 'admission-observation.json', {'classification': 'REAL_HUB_ADMISSION_PROCESS_BARRIER_DI',
            'action': action, 'before_raw': self.before, 'after_raw': after,
            'wall_samples': self.wall_samples, 'only_stable_projection_exclusion': 'core_snapshot.counters.wall_minutes',
            'response': response, 'error': None if error is None else
                {'type': type(error).__name__, 'message': redact(str(error))},
            'method_entries': calls, 'trace': self.trace, 'checks': checks,
            'process_targets_executed': 0, 'native_provider_calls': 0})
        print('FIXTURE_READY: real public wrapper/core, raw accounting and idle noStop/SQL/mainbytes calibrated')
        failures = [key for key, value in checks.items() if not value]
        assert not failures, 'HOST_ADMISSION_AFTER_CLOSE: ' + ', '.join(failures)


def _closed(root, monkeypatch, action):
    fixture = _Fixture(root, monkeypatch)
    fixture.close()
    fixture.assert_fenced(action, fixture.call(action))


def _interleaving(root, monkeypatch, action):
    fixture = _Fixture(root, monkeypatch)
    barrier = {name: threading.Event() for name in ('retrieved', 'release')}
    finished, closed = threading.Event(), threading.Event()
    results, close_errors = [], []

    def caller():
        try:
            results.append(fixture.call(action, barrier=barrier))
        finally:
            finished.set()

    def closer():
        try:
            fixture.close()
        except BaseException as exc:
            close_errors.append(type(exc).__name__)
        finally:
            closed.set()

    calling = threading.Thread(target=caller, daemon=True)
    closing = threading.Thread(target=closer, daemon=True)
    calling.start()
    try:
        assert barrier['retrieved'].wait(1) and fixture.session.thread is None and not finished.is_set()
        closing.start()
        assert closed.wait(1) and not close_errors and fixture.close_returned and not finished.is_set()
        fixture.note('barrier.release_after_completed_idle_close')
    finally:
        barrier['release'].set()
        calling.join(2)
        if closing.ident is not None:
            closing.join(2)
    assert not calling.is_alive() and not closing.is_alive() and len(results) == 1
    order = {event['kind']: event['order'] for event in fixture.trace}
    assert order['caller.real_lookup_returned_before_admission'] < order['close.return_idle']
    assert order['close.return_idle'] < order['barrier.release_after_completed_idle_close']
    assert order['barrier.release_after_completed_idle_close'] < order['caller.continues_only_after_completed_close']
    fixture.assert_fenced(action, results[0])


def test_idle_closed_start_rejects_before_durable_control_or_process(tmp_path, monkeypatch):
    _closed(tmp_path, monkeypatch, 'start')


def test_idle_closed_preparation_rejects_before_durable_request_or_process(tmp_path, monkeypatch):
    _closed(tmp_path, monkeypatch, 'prepare')


def test_start_real_lookup_return_then_idle_close_fences_late_admission(tmp_path, monkeypatch):
    _interleaving(tmp_path, monkeypatch, 'start')


def test_prepare_real_lookup_return_then_idle_close_fences_late_admission(tmp_path, monkeypatch):
    _interleaving(tmp_path, monkeypatch, 'prepare')
