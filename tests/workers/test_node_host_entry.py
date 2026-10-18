"""Frozen entry-proof protocol fixtures: real local stdlib loops, no models.

No production receipt fields are invented. service_actions is the existing
public hook. Wrong-thread/manual-hook and cooperative-controller waits are
explicit scheduling fixtures, not real worker or two-process evidence.
"""
from contextlib import contextmanager
import http.client
import inspect
import json
import os
from pathlib import Path
import socketserver
import sys
import threading
import time
from types import MethodType

from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.node_gateway import NodeGateway
from sisyfus.workers.protocol import digest
from test_lead_mission import make_spec


def _save(root, name, value):
    with (root / name).open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def _until(condition, seconds=1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(.005)
    return condition()


@contextmanager
def _no_global_frames():
    active = {'value': True}
    attempts = []

    def audit(event, args):
        if active['value'] and event == 'sys._current_frames':
            attempts.append(event)
            raise AssertionError('HOST_ENTRY_GLOBAL_FRAME_SCAN')

    sys.addaudithook(audit)
    try:
        yield
    finally:
        active['value'] = False
        assert attempts == [], 'entry proof scanned global task frames'


def _api(hub):
    for name in ('attach_node_gateway', 'detach_node_gateway', 'node_gateway_state'):
        assert callable(getattr(hub, name, None)), 'HOST_ENTRY_API_MISSING: ' + name
    signature = inspect.signature(hub.attach_node_gateway)
    assert signature.parameters['serve_thread'].kind is inspect.Parameter.KEYWORD_ONLY


def _state(hub):
    state = hub.node_gateway_state()
    assert set(state) == {'gateway', 'effective_ready', 'basis'}
    assert type(state['effective_ready']) is bool and isinstance(state['basis'], str)
    return state


def _anonymous(gateway):
    connection = http.client.HTTPConnection('127.0.0.1', gateway.server_port, timeout=1)
    try:
        connection.request('POST', '/node/v1/mission/claim',
            body='{"request_id":"fixture_host_entry_0001"}',
            headers={'Host': '127.0.0.1:' + str(gateway.server_port),
                     'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read(32_001)
        assert response.status == 401 and len(body) <= 32_000
        assert isinstance(json.loads(body), dict)
    finally:
        connection.close()


class _Loop:
    def __init__(self, hub, root, label, *, fault=None, blocking=None):
        self.gateway = NodeGateway(hub, port=0)
        self.first_normal_hook = threading.Event()
        self.errors = []
        self.calibration = None
        self.original = self.gateway.service_actions
        assert self.gateway.serve_forever.__func__ is socketserver.BaseServer.serve_forever
        assert self.gateway.serve_forever.__self__ is self.gateway

        def actions(server):
            self.original()
            if fault is not None and fault.is_set():
                raise HookFault('fixture original service_actions failure')
            if blocking is not None and blocking['armed'].is_set():
                blocking['entered'].set()
                if not blocking['release'].wait(3):
                    raise AssertionError('fixture original-hook release bound')
            if self.calibration is None:
                frame = sys._getframe(1)
                try:
                    self.calibration = {
                        'direct_stdlib_caller': frame.f_code is socketserver.BaseServer.serve_forever.__code__,
                        'exact_gateway_self': frame.f_locals.get('self') is server,
                        'exact_thread_object': threading.current_thread() is self.thread}
                finally:
                    del frame  # No frame/locals retained in fixture data.
                self.first_normal_hook.set()

        self.gateway.service_actions = MethodType(actions, self.gateway)
        self.pre_attach_hook = self.gateway.service_actions
        self.thread = threading.Thread(target=self.gateway.serve_forever,
            kwargs={'poll_interval': .005}, name='fixture-direct-loop-' + label, daemon=True)
        self.thread.start()
        assert self.first_normal_hook.wait(1), 'real loop calibration must reach normal original hook'
        assert all(self.calibration.values()) and self.thread.is_alive()
        _anonymous(self.gateway)
        _save(root, 'real-loop-' + label + '.json', {'classification': 'REAL_SAME_PROCESS_STDLIB_LISTENER_CALIBRATION',
            'url': self.gateway.url, 'calibration': self.calibration,
            'anonymous401': True, 'native_provider_or_two_process_proof': False})
        print('FIXTURE_READY: actual BaseServer direct caller/self + exact Thread; anonymous401; ' + label)

    def close(self):
        # Teardown belongs to this fixture, not to Hub or a foreign attachment.
        if self.thread.is_alive():
            self.gateway.shutdown()
        self.thread.join(2)
        self.gateway.server_close()
        assert not self.thread.is_alive()


class HookFault(RuntimeError):
    pass


@contextmanager
def _loops(root, *, count=1, fault=None, blocking=None):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1'
    hub = MissionHub(root / 'hub')
    loops = []
    try:
        for index in range(count):
            loops.append(_Loop(hub, root, str(index), fault=fault, blocking=blocking))
        with _no_global_frames():
            yield hub, loops
    finally:
        if blocking is not None:
            blocking['release'].set()
        hub.close()
        for loop in reversed(loops):
            loop.close()


def _mission(hub, root):
    spec_root = root / 'fixed-input'
    spec_root.mkdir()
    ident = hub.create(make_spec(spec_root))['id']
    session = hub._session(ident)
    view = hub.snapshot(ident)
    assert set(view) == {'id', 'snapshot', 'controller', 'controls'}
    # Snapshot counters include elapsed wall time: save one projection, never
    # demand full equality between sequential live snapshots.
    _save(root, 'core-input-snapshot.json', view)
    assert view['snapshot']['all_verified'] is False and view['controls'] == []
    return ident, session.mission, session


def _attach(hub, gateway, thread):
    completed = threading.Event()
    result, errors = [], []

    def caller():
        try:
            result.append(hub.attach_node_gateway(gateway, serve_thread=thread))
        except BaseException as exc:
            errors.append(exc)
        finally:
            completed.set()

    calling = threading.Thread(target=caller, name='fixture-bounded-attach', daemon=True)
    with _no_global_frames():
        calling.start()
        assert completed.wait(3), 'HOST_ENTRY_ATTACH_UNBOUNDED: finite attachment required'
        calling.join(1)
        assert not calling.is_alive()
    return result, errors


def _accepted(hub, loop):
    result, errors = _attach(hub, loop.gateway, loop.thread)
    assert not errors and len(result) == 1
    state = _state(hub)
    assert state['effective_ready'] is True
    assert state['gateway'] == {'url': loop.gateway.url,
        'host': '127.0.0.1:' + str(loop.gateway.server_port)}


def test_direct_stdlib_loop_exact_objects_publish_entry_not_task_truth(tmp_path):
    with _loops(tmp_path) as (hub, loops):
        loop = loops[0]
        _, mission, _ = _mission(hub, tmp_path)
        acceptance = mission.spec['acceptance_hash']
        spec_hash = digest(mission.spec)
        _api(hub)
        _accepted(hub, loop)
        assert mission.remote_execution_ready() is True
        assert mission.spec['acceptance_hash'] == acceptance and digest(mission.spec) == spec_hash
        assert mission.journal.runs() == [] and mission._node_claims is None
        assert mission.snapshot()['all_verified'] is False


def test_unrelated_live_thread_rejected_without_foreign_join_or_shutdown(tmp_path, monkeypatch):
    release = threading.Event()
    unrelated = threading.Thread(target=release.wait, kwargs={'timeout': 4}, daemon=True)
    unrelated.start()
    join = unrelated.join
    attempts = []
    try:
        with _loops(tmp_path) as (hub, loops):
            loop = loops[0]
            _api(hub)
            with monkeypatch.context() as scoped:
                def forbidden_join(timeout=None):
                    attempts.append('foreign.join')
                    raise AssertionError('host joined unrelated ownership')
                def forbidden_shutdown():
                    attempts.append('gateway.shutdown')
                    raise AssertionError('host shut down externally owned listener')
                scoped.setattr(unrelated, 'join', forbidden_join)
                scoped.setattr(loop.gateway, 'shutdown', forbidden_shutdown)
                _, errors = _attach(hub, loop.gateway, unrelated)
                assert errors and isinstance(errors[0], (ValueError, RuntimeError, PermissionError))
                assert _state(hub)['effective_ready'] is False and attempts == []
                assert unrelated.is_alive() and loop.thread.is_alive()
            _accepted(hub, loop)
    finally:
        release.set()
        join(2)
    assert not unrelated.is_alive()


def test_same_hub_other_gateway_serving_thread_is_not_selected_entry(tmp_path):
    with _loops(tmp_path, count=2) as (hub, loops):
        one, two = loops
        assert one.gateway.hub is two.gateway.hub is hub and one.thread is not two.thread
        _api(hub)
        _, errors = _attach(hub, one.gateway, two.thread)
        assert errors and isinstance(errors[0], (ValueError, RuntimeError, PermissionError))
        assert _state(hub)['effective_ready'] is False
        assert one.thread.is_alive() and two.thread.is_alive()
        _accepted(hub, one)


def test_matching_thread_manual_service_actions_caller_is_not_loop_entry(tmp_path, monkeypatch):
    hub = MissionHub(tmp_path / 'hub')
    gateway = NodeGateway(hub, port=0)
    began, release = threading.Event(), threading.Event()
    attempts = []

    def manual():
        began.set()
        while not release.wait(.005):
            gateway.service_actions()  # Not BaseServer.serve_forever caller code.

    thread = threading.Thread(target=manual, daemon=True)
    join = thread.join
    thread.start()
    try:
        assert began.wait(1) and thread.is_alive() and gateway.socket.fileno() >= 0
        _save(tmp_path, 'manual-caller-input.json', {'classification': 'MANUAL_MATCHING_THREAD_NOT_SERVER_LOOP',
            'bound_socket': True, 'live_thread': True, 'actual_loop_entered': False})
        print('FIXTURE_READY: real bound Gateway + live matching manual caller; no serve_forever')
        _api(hub)
        with monkeypatch.context() as scoped:
            def forbidden_shutdown():
                attempts.append('never_entered.shutdown')
                raise AssertionError('never-entered server shutdown would wait forever')
            def forbidden_join(timeout=None):
                attempts.append('wrong_owner.join')
                raise AssertionError('blind join of manual ownership')
            scoped.setattr(gateway, 'shutdown', forbidden_shutdown)
            scoped.setattr(thread, 'join', forbidden_join)
            _, errors = _attach(hub, gateway, thread)
            assert errors and _state(hub)['effective_ready'] is False and attempts == []
    finally:
        release.set()
        join(2)
        hub.close()
        gateway.server_close()  # Bound but never entered: no shutdown.
    assert not thread.is_alive()


def test_hook_replacement_revokes_and_detach_preserves_later_owner(tmp_path):
    with _loops(tmp_path) as (hub, loops):
        loop = loops[0]
        _api(hub)
        _accepted(hub, loop)
        replacement = MethodType(lambda self: None, loop.gateway)
        loop.gateway.service_actions = replacement
        assert _state(hub)['effective_ready'] is False
        hub.detach_node_gateway()
        assert loop.gateway.service_actions is replacement
        assert loop.thread.is_alive()
        _anonymous(loop.gateway)


def test_original_hook_exception_survives_host_hook_and_revokes_proof(tmp_path, monkeypatch):
    armed = threading.Event()
    error_types = []
    monkeypatch.setattr(threading, 'excepthook', lambda args: error_types.append(args.exc_type.__name__))
    with _loops(tmp_path, fault=armed) as (hub, loops):
        loop = loops[0]
        _api(hub)
        _accepted(hub, loop)
        armed.set()
        assert _until(lambda: not loop.thread.is_alive())
        assert error_types == ['HookFault'], 'original hook exception was swallowed'
        assert _state(hub)['effective_ready'] is False


def test_write_tx_callback_has_no_frames_wait_env_io_or_hub_session_lock(tmp_path, monkeypatch):
    with _loops(tmp_path) as (hub, loops):
        _, mission, session = _mission(hub, tmp_path)
        _api(hub)
        _accepted(hub, loops[0])
        locked, release, done = threading.Event(), threading.Event(), threading.Event()
        active = {'thread': None, 'callback': False}
        forbidden, errors, values = [], [], []

        def inside():
            return active['callback'] and active['thread'] == threading.get_ident()

        def deny(kind):
            forbidden.append(kind)
            raise AssertionError('READINESS_CALLBACK_FORBIDDEN: ' + kind)

        def audit(event, args):
            if inside() and (event == 'open' or event.startswith(('sqlite3.', 'socket.connect',
                'socket.bind', 'os.listdir', 'os.scandir', 'subprocess.', 'os.system'))):
                deny(event)

        sys.addaudithook(audit)
        getframe, currentframes, wait = sys._getframe, sys._current_frames, threading.Event.wait
        envgetitem = type(os.environ).__getitem__
        with monkeypatch.context() as scoped:
            def guarded_frame(depth=0):
                if inside():
                    deny('sys._getframe')
                return getframe(depth + 1)
            def guarded_frames():
                deny('sys._current_frames')  # No global frame scans in any entry/callback phase here.
            def guarded_wait(event, timeout=None):
                if inside():
                    deny('Event.wait')
                return wait(event, timeout)
            def guarded_env(mapping, key):
                if inside():
                    deny('ENV')
                return envgetitem(mapping, key)
            scoped.setattr(sys, '_getframe', guarded_frame)
            scoped.setattr(sys, '_current_frames', guarded_frames)
            scoped.setattr(threading.Event, 'wait', guarded_wait)
            scoped.setattr(type(os.environ), '__getitem__', guarded_env)

            def owner():
                with hub._lock, session.lock:
                    locked.set()
                    release.wait(3)

            def callback():
                try:
                    with mission.store._transaction():
                        active.update(thread=threading.get_ident(), callback=True)
                        try:
                            values.append(mission.remote_execution_ready())
                        finally:
                            active['callback'] = False
                except BaseException as exc:
                    errors.append(type(exc).__name__)
                finally:
                    done.set()

            holding = threading.Thread(target=owner, daemon=True)
            calling = threading.Thread(target=callback, daemon=True)
            holding.start()
            try:
                assert locked.wait(1)
                calling.start()
                finished_with_locks_held = done.wait(.5)
            finally:
                active['callback'] = False
                release.set()
                holding.join(2)
                if calling.ident is not None:
                    calling.join(2)
            assert finished_with_locks_held and not errors and not forbidden and values == [True]
        assert not holding.is_alive() and not calling.is_alive()
        assert mission.journal.runs() == [] and mission._node_claims is None


def test_delayed_original_hook_after_completed_close_never_publishes_late_entry(tmp_path):
    blocking = {name: threading.Event() for name in ('armed', 'entered', 'release')}
    with _loops(tmp_path, blocking=blocking) as (hub, loops):
        loop = loops[0]
        _, _, session = _mission(hub, tmp_path)
        _api(hub)
        blocking['armed'].set()
        assert blocking['entered'].wait(1)
        attach_done, close_done = threading.Event(), threading.Event()
        errors = []

        def attaching():
            try:
                hub.attach_node_gateway(loop.gateway, serve_thread=loop.thread)
            except BaseException as exc:
                errors.append(type(exc).__name__)
            finally:
                attach_done.set()

        def closing():
            try:
                hub.close()
            finally:
                close_done.set()

        attaching_thread = threading.Thread(target=attaching, daemon=True)
        closing_thread = threading.Thread(target=closing, daemon=True)
        attaching_thread.start()
        try:
            assert _until(lambda: loop.gateway.service_actions is not loop.pre_attach_hook)
            assert not attach_done.is_set()
            assert hub._lock.acquire(blocking=False), 'attachment wait held the Hub lock'
            hub._lock.release()
            assert session.lock.acquire(blocking=False), 'attachment wait held the session lock'
            session.lock.release()
            assert _state(hub)['effective_ready'] is False
            closing_thread.start()
            assert close_done.wait(1), 'close blocked behind entry handshake'
        finally:
            blocking['release'].set()
            attaching_thread.join(3)
            if closing_thread.ident is not None:
                closing_thread.join(2)
        assert not attaching_thread.is_alive() and not closing_thread.is_alive()
        assert attach_done.is_set() and errors and _state(hub)['effective_ready'] is False
        _anonymous(loop.gateway)
        assert loop.thread.is_alive(), 'close must not destroy externally owned listener'


def test_real_gateway_remains_live_during_cooperative_active_controller_drain(tmp_path):
    with _loops(tmp_path) as (hub, loops):
        _, mission, session = _mission(hub, tmp_path)
        _api(hub)
        _accepted(hub, loops[0])
        release, began, done = threading.Event(), threading.Event(), threading.Event()

        def protocol_wait():
            began.set()
            release.wait(3)  # Process-wait DI, not Mission.run/native execution.

        active = threading.Thread(target=protocol_wait, daemon=True)
        session.thread = active
        active.start()

        def closing():
            try:
                hub.close()
            finally:
                done.set()

        closing_thread = threading.Thread(target=closing, daemon=True)
        try:
            assert began.wait(1)
            closing_thread.start()
            assert _until(mission.stop.is_set) and not done.is_set()
            assert _state(hub)['effective_ready'] is False and mission.remote_execution_ready() is False
            _anonymous(loops[0].gateway)
            assert loops[0].thread.is_alive()
        finally:
            release.set()
            active.join(2)
            if closing_thread.ident is not None:
                closing_thread.join(2)
        assert done.is_set() and not active.is_alive() and not closing_thread.is_alive()
        assert mission.journal.runs() == []
