"""STATIC DRAFT: Main-selected N6 SOURCE-01 through SOURCE-06 boundaries.

Freeze and any execution require a separate Main gate. Only real local sockets,
stdlib Threads, public Hub/CLI entry, and explicitly labelled fault/scheduling
fixtures are used. No provider, worker, verifier, integration, or device proof.
"""
from __future__ import annotations

import copy
import ast
import hashlib
import http.client
import json
from pathlib import Path
from socketserver import BaseServer
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from sisyfus.workers import lead_cli, lead_console, node_gateway
from sisyfus.workers.lead_console import LeadConsole, MissionHub
from sisyfus.workers.lead_mission import LeadMission
from test_lead_mission import make_spec


REAL_THREAD = threading.Thread
REAL_SERVE = BaseServer.serve_forever
REAL_GATEWAY = node_gateway.NodeGateway
REAL_GETFRAME = sys._getframe
CLOCKS = (time.time, time.monotonic, time.perf_counter)


def _save(root, name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                      allow_nan=False) + '\n').encode()
    with (root / name).open('xb') as stream:
        stream.write(raw)


def _objects(text):
    decoder, offset, result = json.JSONDecoder(), 0, []
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset == len(text):
            break
        value, offset = decoder.raw_decode(text, offset)
        assert isinstance(value, dict), 'FIXTURE_PUBLIC_JSON_OBJECT_REQUIRED'
        result.append(value)
    return result


def _socket(sock):
    if sock is None:
        return {'captured': False}
    fact = {'captured': True, 'object_id': id(sock), 'fileno': sock.fileno()}
    try:
        fact['address'] = list(sock.getsockname())
    except OSError as exc:
        fact['address_error'] = {'type': type(exc).__name__, 'errno': exc.errno}
    fact['closed'] = fact['fileno'] == -1 and fact.get('address_error', {}).get('errno') == 9
    return fact


def _listener(hub):
    value = hub.node_gateway_state()
    assert set(value) == {'gateway', 'effective_ready', 'basis'}
    assert type(value['effective_ready']) is bool and isinstance(value['basis'], str)
    return value


def _anonymous(root, gateway, label):
    """Actual unauthenticated request: no mission DB/backend or enrollment."""
    connection = http.client.HTTPConnection('127.0.0.1', gateway.server_port, timeout=1)
    try:
        connection.request('GET', '/node/v1/fixture/status', headers={
            'Host': '127.0.0.1:' + str(gateway.server_port), 'Connection': 'close'})
        response = connection.getresponse()
        body = response.read(4097)
        with (root / (label + '.bytes')).open('xb') as stream:
            stream.write(body)
        assert response.status == 401 and len(body) <= 4096
        assert isinstance(json.loads(body), dict)
        return {'status': response.status, 'bytes': len(body),
                'sha256': hashlib.sha256(body).hexdigest(), 'credential_sent': False}
    finally:
        connection.close()


def _source_pins():
    return {str(Path(module.__file__).resolve()): hashlib.sha256(
        Path(module.__file__).read_bytes()).hexdigest()
        for module in (lead_cli, lead_console, node_gateway)}


def _input(root, case, **fields):
    _save(root, 'input.json', {'case': case, 'classification': 'SAME_PROCESS_PROTOCOL_FIXTURE',
        'requested_implementer': 'gpt-6.1-sol', 'runtime_attestation': 'separate',
        'source_pins': _source_pins(), 'real_clock_unchanged': True,
        'native_provider_worker_check_review_integration_calls': 0, **fields})


def _cli_text(root, captured, console=None):
    # No real credentials exist. The real Console generates a fixture-only
    # operator fragment; do not retain that incidental token in the stdout copy.
    text = captured.out
    if console is not None:
        text = text.replace(console.token, '[FIXTURE_TOKEN]')
    _save(root, 'public-cli-output.json', {'stdout_fixture_token_filtered': text,
        'stderr_exact': captured.err, 'stderr_objects': _objects(captured.err),
        'stdout_only_filter': 'generated fixture Console token'})
    return _objects(captured.err)


def _closed_resources(fact):
    assert fact['console_socket']['closed'], 'HOST_REVIEW_ORIGINAL_CONSOLE_SOCKET_OPEN'
    assert fact['gateway_socket']['closed'], 'HOST_REVIEW_ORIGINAL_GATEWAY_SOCKET_OPEN'
    assert not fact['gateway_thread_alive'], 'HOST_REVIEW_OWNED_LOOP_SURVIVED_BEFORE_RESCUE'


def test_source01_extra_interrupts_keep_real_gateway_during_captured_controller_drain(
        tmp_path, monkeypatch, capsys):
    """Real Hub Start/capture; only the core run body is a waiting protocol fixture."""
    owner = threading.current_thread()
    state = SimpleNamespace(hub=None, mission=None, console=None, gateway=None,
        console_socket=None, gateway_socket=None, gateway_thread=None, controller_thread=None,
        controller_entered=threading.Event(), release_controller=threading.Event(),
        join_interrupted=threading.Event(), main_done=threading.Event(), observer_done=threading.Event(),
        interrupts=[], run_calls=0, controller_timeout=False, original_hook_calls=0,
        startup=None, drain=None, exit_code=None, main_error=None, fixture_errors=[], phase='CLI')
    fixed = tmp_path / 'fixed-input'; fixed.mkdir()
    spec = make_spec(fixed)
    spec_path = tmp_path / 'operator-fixture-spec.json'
    with spec_path.open('x') as stream:
        stream.write(json.dumps(spec, allow_nan=False))
    _input(tmp_path, 'SOURCE-01', public_entry='CLI.main(up)+Hub.create/start/close',
        fixture_run='ControlledMission.run: Event wait only, no LeadMission.run call',
        real_fixture_store_only=True, extra_join_interrupts_before_real_join=2,
        observer_window_seconds=.25, proposed_completed_cooperative_exit=130)

    class ControlledMission(LeadMission):
        def __init__(self, directory, spec=None):
            super().__init__(directory, spec)
            state.mission = self
            _save(tmp_path, 'bound-core-before-start.json', {
                'snapshot': self.snapshot(), 'spec': copy.deepcopy(self.spec),
                'native_runs': self.journal.runs(), 'run_kind': 'SCRIPTED_CONTROLLER_DRAIN_ONLY'})

        def run(self, max_cycles=None):
            assert max_cycles == 1
            state.run_calls += 1
            state.controller_thread = threading.current_thread()
            state.controller_entered.set()
            # The bounded hold models an outstanding cooperative drain, not a
            # worker/provider call or a receipt. The observer releases it only
            # after retaining the measured live-controller boundary.
            if not state.release_controller.wait(8):
                state.controller_timeout = True
                raise TimeoutError('FIXTURE_CONTROLLER_RELEASE_BOUND')
            return {'all_verified': False}  # No task/receipt/integration success invented.

    def hub_constructor(directory, *, single=False, mission_factory=None):
        assert mission_factory is None and single is True
        state.hub = MissionHub(directory, single=single, mission_factory=ControlledMission)
        return state.hub

    class CaptureConsole(LeadConsole):
        def __init__(self, hub, *, port):
            super().__init__(hub, port=port)
            state.console, state.console_socket = self, self.socket

        def serve_forever(self, poll_interval=.5):
            assert state.controller_entered.wait(2), 'FIXTURE_REAL_CONTROLLER_TARGET_NOT_ENTERED'
            view = state.hub.snapshot('mission')
            assert set(view) == {'id', 'snapshot', 'controller', 'controls'}
            assert view['controller']['running'] is True
            state.startup = {'snapshot': view, 'listener': _listener(state.hub),
                'anonymous401': _anonymous(tmp_path, state.gateway, 'startup-anonymous401'),
                'controller_thread_id': id(state.controller_thread),
                'gateway_thread_id': id(state.gateway_thread),
                'controller_alive': state.controller_thread.is_alive()}
            _save(tmp_path, 'real-startup-before-console-interrupt.json', state.startup)
            assert state.startup['listener']['effective_ready'] is True
            raise KeyboardInterrupt('FIXTURE_FIRST_CONSOLE_INTERRUPT')

    class CaptureGateway(REAL_GATEWAY):
        def __init__(self, hub, *, port=0):
            super().__init__(hub, port=port)
            state.gateway, state.gateway_socket = self, self.socket
            assert self.serve_forever.__func__ is REAL_SERVE

        def service_actions(self):
            assert threading.current_thread() is state.gateway_thread
            state.original_hook_calls += 1
            super().service_actions()

    class CapturedThread(REAL_THREAD):
        def __init__(self, group=None, target=None, name=None, args=(), kwargs=None,
                     *, daemon=None, context=None):
            options = dict(kwargs or {})
            if name == 'techlead-node-gateway':
                if getattr(target, '__self__', None) is state.gateway:
                    assert target.__func__ is REAL_SERVE
                    options['poll_interval'] = .01
                state.gateway_thread = self
            super().__init__(group=group, target=target, name=name, args=args,
                             kwargs=options, daemon=daemon, **({'context': context} if context is not None else {}))

        def join(self, timeout=None):
            # Inject at this captured real Thread's public join boundary only.
            # Never touch _started/_tstate_lock/_handle or override is_alive.
            if (self is state.controller_thread and threading.current_thread() is owner
                    and state.phase == 'CLI' and len(state.interrupts) < 2):
                state.interrupts.append({'ordinal': len(state.interrupts) + 1,
                    'actual_thread_id': id(self), 'alive': self.is_alive(),
                    'real_join_not_yet_called': True, 'at': time.monotonic()})
                state.join_interrupted.set()
                raise KeyboardInterrupt('FIXTURE_ADDITIONAL_DRAIN_INTERRUPT')
            return super().join(timeout)

    proxy = SimpleNamespace(**vars(threading)); proxy.Thread = CapturedThread
    monkeypatch.setattr(lead_cli, 'MissionHub', hub_constructor)
    monkeypatch.setattr(lead_cli, 'LeadConsole', CaptureConsole)
    monkeypatch.setattr(lead_cli, 'threading', proxy)
    monkeypatch.setattr(lead_console, 'threading', proxy)
    monkeypatch.setattr(node_gateway, 'NodeGateway', CaptureGateway)

    def observe_then_release():
        try:
            if not state.join_interrupted.wait(3):
                state.fixture_errors.append('FIXTURE_DRAIN_JOIN_INTERRUPTION_NOT_REACHED')
                return
            main_returned = state.main_done.wait(.25)
            hub, controller = state.hub, state.controller_thread
            fact = {'at': time.monotonic(), 'main_returned_while_controller_held': main_returned,
                'captured_controller_thread_id': id(controller), 'controller_alive': controller.is_alive(),
                'real_controller_stop_event': state.mission.stop.is_set(),
                'Hub_closing': hub._closing, 'Hub_closed': hub._closed,
                'Hub_close_done': hub._close_done.is_set(), 'listener': _listener(hub),
                'original_gateway_socket': _socket(state.gateway_socket),
                'gateway_thread_alive': state.gateway_thread.is_alive(),
                'fixture_completion_signal_already_sent': state.release_controller.is_set(),
                'interrupts_at_boundary': copy.deepcopy(state.interrupts)}
            try:
                fact['drain_anonymous401'] = _anonymous(tmp_path, state.gateway, 'drain-anonymous401')
            except (OSError, http.client.HTTPException) as exc:
                fact['drain_http_error'] = {'type': type(exc).__name__}
            state.drain = fact
            _save(tmp_path, 'drain-before-fixture-controller-release.json', fact)
        except BaseException as exc:
            state.fixture_errors.append('OBSERVER_' + type(exc).__name__)
        finally:
            # Independent fixture completion, not an implementation close fact.
            state.release_controller.set()
            state.observer_done.set()

    observer = REAL_THREAD(target=observe_then_release, name='fixture-drain-boundary-observer', daemon=True)
    observer.start()
    try:
        state.exit_code = lead_cli.main(['up', '--directory', str(tmp_path / 'hub'),
            '--port', '0', '--node-gateway-port', '0', '--allow-local-workers',
            '--max-cycles', '1', str(spec_path)])
    except BaseException as exc:
        state.main_error = {'type': type(exc).__name__}
    finally:
        state.main_done.set()
        observer.join(4)
        pre = {'exit_code': state.exit_code, 'main_error': state.main_error,
            'console_socket': _socket(state.console_socket), 'gateway_socket': _socket(state.gateway_socket),
            'gateway_thread_alive': bool(state.gateway_thread and state.gateway_thread.is_alive()),
            'controller_thread_alive': bool(state.controller_thread and state.controller_thread.is_alive()),
            'observer_alive': observer.is_alive(), 'fixture_errors': state.fixture_errors[:],
            'recorded_controller_completion_signal': state.release_controller.is_set()}
        _save(tmp_path, 'CLI-return-before-fallback-rescue.json', pre)
        captured = capsys.readouterr()
        records = _cli_text(tmp_path, captured, state.console)
        state.phase = 'FIXTURE_RESCUE'
        rescued = []
        state.release_controller.set()
        if state.controller_thread is not None:
            if state.controller_thread.is_alive():
                rescued.append('owned_controller_completion_and_join')
                REAL_THREAD.join(state.controller_thread, 2)
        if state.gateway_thread is not None:
            if state.gateway_thread.is_alive():
                assert state.startup is not None and state.startup['anonymous401']['status'] == 401
                rescued.append('owned_proven_entered_gateway_shutdown_and_join')
                BaseServer.shutdown(state.gateway)
                REAL_THREAD.join(state.gateway_thread, 2)
        if state.gateway is not None:
            state.hub.detach_node_gateway()
            REAL_GATEWAY.server_close(state.gateway)
        if state.console is not None:
            LeadConsole.server_close(state.console)
        observer.join(1)
        _save(tmp_path, 'fixture-rescue.json', {'rescued_resources': rescued,
            'observer_alive_after': observer.is_alive(),
            'controller_alive_after': bool(state.controller_thread and state.controller_thread.is_alive()),
            'gateway_alive_after': bool(state.gateway_thread and state.gateway_thread.is_alive()),
            'implementation_cleanup_credit': False})
        if state.mission is not None:
            _save(tmp_path, 'core-after-fixture-controller-drain.json', {
                'snapshot': state.mission.snapshot(), 'native_runs': state.mission.journal.runs(),
                'acceptance_hash': state.mission.spec['acceptance_hash'],
                'fixed_input_bytes': {str(p.relative_to(fixed)): {
                    'bytes': len(p.read_bytes()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in sorted(fixed.rglob('*')) if p.is_file()},
                'run_calls': state.run_calls, 'controller_timeout': state.controller_timeout})
    assert state.startup is not None and state.run_calls == 1, 'FIXTURE_REAL_START_NOT_CALIBRATED'
    assert state.drain is not None and not state.fixture_errors, 'FIXTURE_DRAIN_OBSERVATION_MISSING'
    assert state.drain['controller_alive'] and not state.drain['fixture_completion_signal_already_sent']
    assert state.drain['real_controller_stop_event'] is True
    assert not state.drain['Hub_closed'] and not state.drain['Hub_close_done'], 'HOST_REVIEW_CLOSE_DONE_WITH_LIVE_CAPTURED_THREAD'
    assert not state.drain['main_returned_while_controller_held'], 'HOST_REVIEW_MAIN_RETURNED_BEFORE_CONTROLLER_DRAIN'
    assert state.drain['listener']['gateway'] is not None, 'HOST_REVIEW_GATEWAY_DETACHED_DURING_DRAIN'
    assert state.drain['listener']['effective_ready'] is False  # Closing revokes new admission, not transport.
    assert state.drain['original_gateway_socket']['fileno'] >= 0 and state.drain['gateway_thread_alive']
    assert state.drain.get('drain_anonymous401', {}).get('status') == 401, 'HOST_REVIEW_GATEWAY_NOT_SERVING_DRAIN'
    assert len(state.interrupts) == 2 and not state.controller_timeout
    _closed_resources(pre)
    assert pre['controller_thread_alive'] is False and state.main_error is None
    assert state.exit_code == 130, 'HOST_REVIEW_COOPERATIVE_INTERRUPT_EXIT_CHANGED'
    assert not records
    assert state.mission.journal.runs() == [] and state.mission.snapshot()['all_verified'] is False
    assert state.mission.spec['acceptance_hash'] == json.loads(
        (tmp_path / 'bound-core-before-start.json').read_text())['spec']['acceptance_hash']
    assert CLOCKS == (time.time, time.monotonic, time.perf_counter)


@pytest.mark.parametrize('fault_site', ('getframe', 'locals'))
def test_source03_real_hook_witness_fault_signals_and_propagates_before_deadline(
        fault_site, tmp_path, monkeypatch):
    _input(tmp_path, 'SOURCE-03-' + fault_site, public_entry='Hub.attach_node_gateway',
        fault_namespace='lead_console.sys only', controlled_fault=fault_site,
        post_propagation_outer_fixture_thread_hold=True, proposed_attach_bound_seconds=.5)
    hub = MissionHub(tmp_path / 'empty-hub')
    state = SimpleNamespace(ready=threading.Event(), fault_caught=threading.Event(),
        release=threading.Event(), errors=[], original_calls=0, original_after_fault=0,
        fault_metadata=None, propagated_identity=False, thread=None, run_entered=threading.Event())
    expected = ValueError('FIXTURE_WITNESS_INTROSPECTION_FAULT')

    class CaptureGateway(REAL_GATEWAY):
        def service_actions(self):
            state.original_calls += 1
            if state.fault_metadata is not None:
                state.original_after_fault += 1
            super().service_actions()
            state.ready.set()

    gateway = CaptureGateway(hub, port=0)
    original_socket = gateway.socket
    assert gateway.serve_forever.__func__ is REAL_SERVE

    class OwnLoopThread(REAL_THREAD):
        def run(self):
            state.run_entered.set()
            try:
                super().run()  # Actual supplied BaseServer.serve_forever target.
            except BaseException as exc:
                state.propagated_identity = exc is expected
                state.errors.append({'type': type(exc).__name__, 'same_exception_object': exc is expected})
                state.fault_caught.set()
                # Keep the actual Thread alive outside the exited loop so
                # attach cannot mask missing failed/changed via is_alive=False.
                if not state.release.wait(4):
                    state.errors.append({'type': 'FIXTURE_OUTER_RELEASE_BOUND'})

    state.thread = OwnLoopThread(target=gateway.serve_forever, kwargs={'poll_interval': .01},
                                 name='fixture-witness-owned-loop', daemon=True)
    thread = state.thread
    returned, attach_error, elapsed, pre = None, None, None, None

    class FaultLocals:
        f_code = REAL_SERVE.__code__

        @property
        def f_locals(self):
            raise expected

    def fault_frame(depth):
        assert depth == 1
        # One fixed known caller depth, never a global stack scan. Copy scalar
        # witness facts and discard the real frame before faulting.
        frame = REAL_GETFRAME(2)
        try:
            state.fault_metadata = {'actual_direct_stdlib_caller': frame.f_code is REAL_SERVE.__code__,
                'actual_exact_gateway_self': frame.f_locals.get('self') is gateway,
                'actual_owned_thread': threading.current_thread() is thread,
                'fault_site': fault_site, 'frame_or_locals_retained': False}
        finally:
            del frame
        if fault_site == 'getframe':
            raise expected
        return FaultLocals()  # Only the explicitly injected f_locals fault view.

    try:
        thread.start()
        assert state.ready.wait(1) and thread.is_alive(), 'FIXTURE_REAL_NORMAL_LOOP_NOT_REACHED'
        anonymous = _anonymous(tmp_path, gateway, 'normal-loop-anonymous401')
        proxy = SimpleNamespace(**vars(sys)); proxy._getframe = fault_frame
        monkeypatch.setattr(lead_console, 'sys', proxy)
        started = time.monotonic()
        try:
            returned = hub.attach_node_gateway(gateway, serve_thread=thread)
        except BaseException as exc:
            attach_error = {'type': type(exc).__name__, 'message': str(exc)}
        elapsed = time.monotonic() - started
        assert state.fault_caught.wait(.2), 'FIXTURE_WITNESS_FAULT_NOT_PROPAGATED_FROM_REAL_LOOP'
        entry = hub._gateway_observation  # Supplemental internal signal facts, not a public alias.
        pre = {'public_result': returned, 'public_attach_error': attach_error,
            'elapsed_seconds': elapsed, 'listener': _listener(hub),
            'owned_thread_alive_outside_exited_loop': thread.is_alive(),
            'original_gateway_socket': _socket(original_socket), 'anonymous401': anonymous,
            'propagated_same_exception_object': state.propagated_identity,
            'fault_metadata': state.fault_metadata, 'outer_thread_errors': state.errors[:],
            'entry_failed': entry.failed, 'entry_changed': entry.changed.is_set(),
            'entry_observed': entry.observed, 'entry_entered': entry.entered,
            'original_hook_calls_after_introspection_fault': state.original_after_fault}
        _save(tmp_path, 'witness-before-fixture-release.json', pre)
    finally:
        # The real loop already propagated/ended. No shutdown of this held,
        # non-serving Thread; release only the owned outer fixture handler.
        state.release.set()
        if state.run_entered.is_set():
            thread.join(2)
        hub.detach_node_gateway()
        hub.close()
        gateway.server_close()
        _save(tmp_path, 'fixture-rescue.json', {'rescued_resources': ['owned_outer_fault_handler_release'],
            'thread_alive_after': thread.is_alive(), 'original_socket_after': _socket(original_socket),
            'loop_shutdown_called': False, 'implementation_cleanup_credit': False})
    assert all(pre['fault_metadata'][key] for key in
               ('actual_direct_stdlib_caller', 'actual_exact_gateway_self', 'actual_owned_thread'))
    assert pre['propagated_same_exception_object'] and pre['owned_thread_alive_outside_exited_loop']
    assert pre['entry_failed'] and pre['entry_changed'], 'HOST_REVIEW_WITNESS_FAULT_MISSING_FAILED_CHANGED'
    assert not pre['entry_observed'] and not pre['entry_entered'] and pre['original_hook_calls_after_introspection_fault'] == 0
    assert elapsed < .5, 'HOST_REVIEW_WITNESS_FAULT_WAITED_FULL_ENTRY_DEADLINE'
    assert attach_error == {'type': 'RuntimeError', 'message': 'gateway loop entry failed or serving Thread did not match'}
    assert returned is None and pre['listener']['gateway'] is None and pre['listener']['effective_ready'] is False
    assert not thread.is_alive() and CLOCKS == (time.time, time.monotonic, time.perf_counter)


def test_source05_interrupt_status_emit_failure_keeps_all_real_cleanup_diagnostics(
        tmp_path, monkeypatch, capsys):
    _input(tmp_path, 'SOURCE-05', public_entry='CLI.main(hub)', status_emit_fault='BrokenPipeError',
        cleanup_faults_after_actual_original_returns=[
            'hub.close', 'hub.detach', 'gateway.shutdown', 'gateway.thread.join', 'gateway.close', 'console.close'])
    state = SimpleNamespace(hub=None, console=None, gateway=None, thread=None,
        console_socket=None, gateway_socket=None, faults=[], emitted=[], original_calls=0,
        original_entered=threading.Event(), phase='CLI', status_faults=0, startup=None)
    original_emit = lead_cli.emit

    def fault(operation):
        state.faults.append({'operation': operation, 'after_actual_original_return': True,
                             'at': time.monotonic()})
        raise RuntimeError('FIXTURE_CLEAN_FAILURE_' + operation.replace('.', '_'))

    class CaptureHub(MissionHub):
        def __init__(self, directory, *, single=False, mission_factory=None):
            super().__init__(directory, single=single, mission_factory=mission_factory)
            state.hub = self

        def close(self):
            super().close()
            if state.phase == 'CLI':
                fault('hub.close')

        def detach_node_gateway(self):
            super().detach_node_gateway()
            if state.phase == 'CLI':
                fault('hub.detach')

    class CaptureConsole(LeadConsole):
        def __init__(self, hub, *, port):
            super().__init__(hub, port=port)
            state.console, state.console_socket = self, self.socket

        def serve_forever(self, poll_interval=.5):
            assert _listener(state.hub)['effective_ready'] is True
            state.startup = _anonymous(tmp_path, state.gateway, 'normal-owned-loop-anonymous401')
            raise KeyboardInterrupt('FIXTURE_CONSOLE_INTERRUPT')

        def server_close(self):
            super().server_close()
            if state.phase == 'CLI':
                fault('console.close')

    class CaptureGateway(REAL_GATEWAY):
        def __init__(self, hub, *, port=0):
            super().__init__(hub, port=port)
            state.gateway, state.gateway_socket = self, self.socket
            assert self.serve_forever.__func__ is REAL_SERVE

        def service_actions(self):
            assert threading.current_thread() is state.thread
            state.original_calls += 1
            super().service_actions()
            state.original_entered.set()

        def shutdown(self):
            assert state.startup and state.startup['status'] == 401
            super().shutdown()
            if state.phase == 'CLI':
                fault('gateway.shutdown')

        def server_close(self):
            super().server_close()
            if state.phase == 'CLI':
                fault('gateway.close')

    class OwnedThread(REAL_THREAD):
        def __init__(self, group=None, target=None, name=None, args=(), kwargs=None,
                     *, daemon=None, context=None):
            options = dict(kwargs or {})
            if name == 'techlead-node-gateway':
                if getattr(target, '__self__', None) is state.gateway:
                    assert target.__func__ is REAL_SERVE
                    options['poll_interval'] = .01
            super().__init__(group=group, target=target, name=name, args=args,
                             kwargs=options, daemon=daemon, **({'context': context} if context is not None else {}))
            if name == 'techlead-node-gateway':
                state.thread = self

        def join(self, timeout=None):
            super().join(timeout)
            if state.phase == 'CLI' and self is state.thread:
                assert not self.is_alive()
                fault('gateway.thread.join')

    def failing_status_emit(value, *, error=False):
        if not error and value.get('terminal') is False and 'status' in value:
            state.status_faults += 1
            raise BrokenPipeError('FIXTURE_CLEAN_INTERRUPT_STATUS_EMIT_FAILURE')
        # Retain each actual diagnostic separately, not an invented collector.
        if error:
            state.emitted.append(copy.deepcopy(value))
        return original_emit(value, error=error)

    proxy = SimpleNamespace(**vars(threading)); proxy.Thread = OwnedThread
    monkeypatch.setattr(lead_cli, 'MissionHub', CaptureHub)
    monkeypatch.setattr(lead_cli, 'LeadConsole', CaptureConsole)
    monkeypatch.setattr(lead_cli, 'threading', proxy)
    monkeypatch.setattr(node_gateway, 'NodeGateway', CaptureGateway)
    exit_code = None
    monkeypatch.setattr(lead_cli, 'emit', failing_status_emit)
    try:
        exit_code = lead_cli.main(['hub', '--directory', str(tmp_path / 'empty-hub'),
                                  '--port', '0', '--node-gateway-port', '0'])
    finally:
        pre = {'exit_code': exit_code, 'console_socket': _socket(state.console_socket),
            'gateway_socket': _socket(state.gateway_socket),
            'gateway_thread_alive': bool(state.thread and state.thread.is_alive()),
            'actual_cleanup_faults': state.faults[:], 'actual_error_emits': state.emitted[:],
            'status_emit_fault_count': state.status_faults, 'startup_anonymous401': state.startup}
        _save(tmp_path, 'all-cleanup-before-fixture-rescue.json', pre)
        captured = capsys.readouterr()
        records = _cli_text(tmp_path, captured, state.console)
        state.phase = 'FIXTURE_RESCUE'
        rescued = []
        if state.thread is not None and state.thread.is_alive():
            assert state.startup and state.startup['status'] == 401
            rescued.append('owned_proven_loop_shutdown_and_join')
            BaseServer.shutdown(state.gateway)
            REAL_THREAD.join(state.thread, 2)
        if state.gateway is not None:
            state.hub.detach_node_gateway()
            REAL_GATEWAY.server_close(state.gateway)
        if state.console is not None:
            LeadConsole.server_close(state.console)
        if state.hub is not None:
            state.hub.close()
        _save(tmp_path, 'fixture-rescue.json', {'rescued_resources': rescued,
            'thread_alive_after': bool(state.thread and state.thread.is_alive()),
            'implementation_cleanup_credit': False})
    assert state.startup and state.startup['status'] == 401 and state.status_faults == 1
    expected = ['hub.close', 'hub.detach', 'gateway.shutdown', 'gateway.thread.join', 'gateway.close', 'console.close']
    assert [item['operation'] for item in state.faults] == expected, 'FIXTURE_ALL_REAL_CLEANUP_BOUNDARIES_NOT_REACHED'
    _closed_resources(pre)
    assert records == state.emitted and exit_code == 1
    by_operation = {item.get('operation'): item for item in records}
    assert set(expected).issubset(by_operation), 'HOST_REVIEW_KBI_EMIT_FAILURE_DROPPED_CLEANUP_DIAGNOSTICS'
    assert [item['operation'] for item in records if item.get('operation') in expected] == expected
    for operation in expected:
        assert by_operation[operation]['error'] == {'type': 'RuntimeError',
            'message': 'FIXTURE_CLEAN_FAILURE_' + operation.replace('.', '_')}
    status_errors = [item for item in records if item.get('error', {}).get('type') == 'BrokenPipeError']
    assert len(status_errors) == 1 and status_errors[0].get('operation') == 'console.interrupt.publish'
    assert status_errors[0]['error']['message'] == 'FIXTURE_CLEAN_INTERRUPT_STATUS_EMIT_FAILURE'
    assert all(item.get('operation') != 'dispatch_or_cooperative_shutdown' for item in records)
    assert 'Traceback' not in captured.err and CLOCKS == (time.time, time.monotonic, time.perf_counter)


@pytest.mark.parametrize('message_kind', ('relative', 'unc', 'clean5005'))
def test_source06_public_bind_diagnostic_paths_and_clean_prefix(
        message_kind, tmp_path, monkeypatch, capsys):
    messages = {'relative': 'open proj/secret.txt failed',
                'unc': r'open \\private_server\private_share\secret.txt failed',
                'clean5005': 'Q' * 5005}
    message = messages[message_kind]
    _input(tmp_path, 'SOURCE-06-' + message_kind, public_entry='CLI.main(hub)',
        actual_fault_stage='console.bind', synthetic_message=message,
        exception_filename_attribute=None, cleanup_real_empty_Hub=True)
    state = SimpleNamespace(hub=None, constructed=False)

    def capture_hub(directory, *, single=False, mission_factory=None):
        state.hub = MissionHub(directory, single=single, mission_factory=mission_factory)
        return state.hub

    class FaultConsole(LeadConsole):
        def __init__(self, hub, *, port):
            # Explicit fault before resource allocation, not a lost socket.
            assert hub is state.hub and port == 0
            state.constructed = True
            raise ValueError(message)

    monkeypatch.setattr(lead_cli, 'MissionHub', capture_hub)
    monkeypatch.setattr(lead_cli, 'LeadConsole', FaultConsole)
    exit_code = lead_cli.main(['hub', '--directory', str(tmp_path / 'empty-hub'), '--port', '0'])
    captured = capsys.readouterr()
    records = _cli_text(tmp_path, captured)
    raw = {'exit_code': exit_code, 'actual_console_constructor_entered': state.constructed,
        'public_listener_after': _listener(state.hub), 'Hub_closed': state.hub._closed,
        'Hub_close_done': state.hub._close_done.is_set(), 'error_records': records,
        'socket_or_Thread_allocated': False, 'fixture_rescue_needed': False}
    _save(tmp_path, 'public-diagnostic-and-cleanup.json', raw)
    assert state.constructed and exit_code == 1 and state.hub._close_done.is_set()
    assert raw['public_listener_after']['gateway'] is None and not raw['public_listener_after']['effective_ready']
    assert len(records) == 1 and records[0].get('operation') == 'console.bind'
    expected_message = ('Q' * 4000 if message_kind == 'clean5005'
                        else 'host lifecycle failure during console.bind')
    assert records[0]['error'] == {'type': 'ValueError', 'message': expected_message}, 'HOST_REVIEW_PRIVATE_PATH_OR_CLEAN_PREFIX_DIAGNOSTIC'
    assert 'Traceback' not in captured.err
    if message_kind != 'clean5005':
        assert 'secret.txt' not in captured.err and 'private_server' not in captured.err
        assert 'private_share' not in captured.err and 'proj/' not in captured.err
    assert CLOCKS == (time.time, time.monotonic, time.perf_counter)


def test_source06_gateway_import_failure_has_exact_public_operation_and_closes_console(
        tmp_path, monkeypatch, capsys):
    _input(tmp_path, 'SOURCE-06-import', public_entry='CLI.main(hub --node-gateway-port 0)',
        controlled_fault='loaded node_gateway public NodeGateway name lookup',
        global_import_function_or_stdlib_changes=False, expected_operation='gateway.import')
    state = SimpleNamespace(hub=None, console=None, original_socket=None, import_faults=0)

    def capture_hub(directory, *, single=False, mission_factory=None):
        state.hub = MissionHub(directory, single=single, mission_factory=mission_factory)
        return state.hub

    class CaptureConsole(LeadConsole):
        def __init__(self, hub, *, port):
            super().__init__(hub, port=port)
            state.console, state.original_socket = self, self.socket

    def fault_name(name):
        if name == 'NodeGateway':
            state.import_faults += 1
            raise ImportError('FIXTURE_CLEAN_GATEWAY_IMPORT_FAILURE')
        raise AttributeError(name)

    monkeypatch.setattr(lead_cli, 'MissionHub', capture_hub)
    monkeypatch.setattr(lead_cli, 'LeadConsole', CaptureConsole)
    # Only this already-loaded owned module's constructor-name lookup is
    # faulted. No global __import__, sys.meta_path/sys.modules or frame patch.
    with monkeypatch.context() as lookup:
        lookup.delattr(node_gateway, 'NodeGateway')
        lookup.setattr(node_gateway, '__getattr__', fault_name, raising=False)
        exit_code = lead_cli.main(['hub', '--directory', str(tmp_path / 'empty-hub'),
                                  '--port', '0', '--node-gateway-port', '0'])
    pre = {'exit_code': exit_code, 'import_fault_count': state.import_faults,
        'console_socket': _socket(state.original_socket), 'listener': _listener(state.hub),
        'Hub_closed': state.hub._closed, 'Hub_close_done': state.hub._close_done.is_set(),
        'gateway_constructed': False, 'owned_gateway_thread_constructed': False,
        'public_import_lookup_restored': node_gateway.NodeGateway is REAL_GATEWAY}
    _save(tmp_path, 'import-before-fixture-rescue.json', pre)
    captured = capsys.readouterr()
    records = _cli_text(tmp_path, captured, state.console)
    rescued = []
    if state.original_socket.fileno() >= 0:
        rescued.append('owned_console_socket_close')
        LeadConsole.server_close(state.console)
    state.hub.close()
    _save(tmp_path, 'fixture-rescue.json', {'rescued_resources': rescued,
        'original_socket_after': _socket(state.original_socket), 'implementation_cleanup_credit': False})
    assert state.import_faults == 1 and exit_code == 1 and pre['public_import_lookup_restored']
    assert pre['console_socket']['closed'] and pre['Hub_close_done']
    assert len(records) == 1
    assert records[0] == {'operation': 'gateway.import',
        'error': {'type': 'ImportError', 'message': 'FIXTURE_CLEAN_GATEWAY_IMPORT_FAILURE'}}, 'HOST_REVIEW_GATEWAY_IMPORT_MISLABELLED_CONSOLE_BIND'
    assert pre['listener']['gateway'] is None and pre['listener']['effective_ready'] is False
    assert 'Traceback' not in captured.err and CLOCKS == (time.time, time.monotonic, time.perf_counter)


def test_source02_blocked_replacement_hook_has_bounded_shutdown_and_explicit_remaining_resources(
        tmp_path, monkeypatch, capsys):
    """Later hook is a controlled block, not a stock semaphore/permit claim."""
    _input(tmp_path, 'SOURCE-02', public_entry='CLI.main(hub)',
        fault='owned public replacement service_actions held by fixture Event',
        shutdown_observation_policy_seconds=2.0, existing_join_policy_seconds=2.0,
        total_shutdown_plus_join_margin_seconds=.4,
        stock_gateway_permit_wait_claim=False, expected_exit=1)
    owner = threading.current_thread()
    state = SimpleNamespace(hub=None, console=None, gateway=None, thread=None,
        console_socket=None, gateway_socket=None, startup=None, replacement=None,
        replacement_entered=threading.Event(), release=threading.Event(),
        shutdown_entered=threading.Event(), main_done=threading.Event(),
        shutdown_thread=None, shutdown_at=None, shutdown_returned=False,
        hook_fact=None, drain=None, close_attempts=[], join_calls=[], errors=[], exit_code=None,
        main_error=None, replacement_expired=False, phase='CLI')

    class CaptureConsole(LeadConsole):
        def __init__(self, hub, *, port):
            super().__init__(hub, port=port)
            state.hub, state.console, state.console_socket = hub, self, self.socket

        def serve_forever(self, poll_interval=.5):
            assert _listener(state.hub)['effective_ready'] is True
            state.startup = _anonymous(tmp_path, state.gateway, 'proven-owned-loop-anonymous401')

            def replacement():
                frame = REAL_GETFRAME(1)
                try:
                    state.hook_fact = {'direct_stdlib_caller': frame.f_code is REAL_SERVE.__code__,
                        'exact_gateway_self': frame.f_locals.get('self') is state.gateway,
                        'exact_owned_Thread': threading.current_thread() is state.thread,
                        'frame_or_locals_retained': False}
                finally:
                    del frame
                state.replacement_entered.set()
                if not state.release.wait(8):
                    state.replacement_expired = True
                    raise TimeoutError('FIXTURE_REPLACEMENT_HOOK_RELEASE_BOUND')

            state.replacement = replacement
            state.gateway.service_actions = replacement
            assert state.replacement_entered.wait(1), 'FIXTURE_REPLACEMENT_NOT_REACHED_IN_REAL_LOOP'
            assert _listener(state.hub)['effective_ready'] is False
            raise KeyboardInterrupt('FIXTURE_CONSOLE_INTERRUPT_WITH_OWNED_BLOCKED_LOOP')

        def server_close(self):
            state.close_attempts.append({'operation': 'console.close', 'phase': state.phase})
            return super().server_close()

    class CaptureGateway(REAL_GATEWAY):
        def __init__(self, hub, *, port=0):
            super().__init__(hub, port=port)
            state.gateway, state.gateway_socket = self, self.socket
            assert self.serve_forever.__func__ is REAL_SERVE

        def shutdown(self):
            assert state.startup and state.startup['status'] == 401
            assert state.replacement_entered.is_set() and all(state.hook_fact[key] for key in
                ('direct_stdlib_caller', 'exact_gateway_self', 'exact_owned_Thread'))
            state.shutdown_thread = threading.current_thread()
            state.shutdown_at = time.monotonic()
            state.shutdown_entered.set()
            super().shutdown()  # Actual public stdlib wait, no private flag access.
            state.shutdown_returned = True

        def server_close(self):
            state.close_attempts.append({'operation': 'gateway.close', 'phase': state.phase})
            return super().server_close()

    class CaptureThread(REAL_THREAD):
        def __init__(self, group=None, target=None, name=None, args=(), kwargs=None,
                     *, daemon=None, context=None):
            options = dict(kwargs or {})
            if name == 'techlead-node-gateway':
                if getattr(target, '__self__', None) is state.gateway:
                    assert target.__func__ is REAL_SERVE
                    options['poll_interval'] = .01
                state.thread = self
            super().__init__(group=group, target=target, name=name, args=args,
                             kwargs=options, daemon=daemon, **({'context': context} if context is not None else {}))

        def join(self, timeout=None):
            if self is state.thread and threading.current_thread() is owner and state.phase == 'CLI':
                state.join_calls.append({'timeout': timeout, 'at': time.monotonic(),
                    'seconds_after_shutdown_call': time.monotonic() - state.shutdown_at,
                    'actual_serve_Thread_alive': self.is_alive()})
            return super().join(timeout)

    proxy = SimpleNamespace(**vars(threading)); proxy.Thread = CaptureThread
    monkeypatch.setattr(lead_cli, 'LeadConsole', CaptureConsole)
    monkeypatch.setattr(lead_cli, 'threading', proxy)
    monkeypatch.setattr(node_gateway, 'NodeGateway', CaptureGateway)

    def observe_then_release():
        try:
            if not state.shutdown_entered.wait(3):
                state.errors.append('FIXTURE_ACTUAL_PUBLIC_SHUTDOWN_NOT_REACHED'); return
            returned = state.main_done.wait(4.4)
            calling = state.shutdown_thread
            state.drain = {'at': time.monotonic(), 'CLI_returned_before_fixture_release': returned,
                'CLI_exit': state.exit_code, 'elapsed_since_actual_shutdown_call': time.monotonic() - state.shutdown_at,
                'shutdown_returned_before_fixture_release': state.shutdown_returned,
                'shutdown_called_in_CLI_owner': calling is owner,
                'shutdown_call_Thread_id': id(calling), 'shutdown_call_Thread_alive': calling.is_alive(),
                'shutdown_call_Thread_daemon': calling.daemon,
                'serve_Thread_alive': state.thread.is_alive(),
                'original_gateway_socket': _socket(state.gateway_socket),
                'original_console_socket': _socket(state.console_socket),
                'close_attempts': copy.deepcopy(state.close_attempts),
                'owned_public_join_calls': copy.deepcopy(state.join_calls),
                'public_listener': _listener(state.hub), 'hook_fact': state.hook_fact,
                'later_hook_owner_preserved': state.gateway.service_actions is state.replacement,
                'fixture_release_already_sent': state.release.is_set()}
            _save(tmp_path, 'blocked-shutdown-before-fixture-release.json', state.drain)
        except BaseException as exc:
            state.errors.append('OBSERVER_' + type(exc).__name__)
        finally:
            state.release.set()  # Only after persisting the measured boundary.

    observer = REAL_THREAD(target=observe_then_release, name='fixture-blocked-shutdown-observer', daemon=True)
    observer.start()
    try:
        state.exit_code = lead_cli.main(['hub', '--directory', str(tmp_path / 'empty-hub'),
                                       '--port', '0', '--node-gateway-port', '0'])
    except BaseException as exc:
        state.main_error = {'type': type(exc).__name__}
    finally:
        state.main_done.set()
        observer.join(6)
        pre = {'exit_code': state.exit_code, 'main_error': state.main_error,
            'gateway_socket': _socket(state.gateway_socket), 'console_socket': _socket(state.console_socket),
            'gateway_thread_alive': bool(state.thread and state.thread.is_alive()),
            'observer_alive': observer.is_alive(), 'fixture_errors': state.errors[:],
            'earlier_boundary_record': 'blocked-shutdown-before-fixture-release.json'}
        _save(tmp_path, 'CLI-return-before-fallback-rescue.json', pre)
        captured = capsys.readouterr()
        records = _cli_text(tmp_path, captured, state.console)
        state.phase = 'FIXTURE_RESCUE'
        state.release.set()
        rescued = ['owned_replacement_hook_release']
        if state.thread is not None and state.thread.is_alive():
            assert state.startup and state.startup['status'] == 401
            if not state.shutdown_entered.is_set():
                BaseServer.shutdown(state.gateway)
            REAL_THREAD.join(state.thread, 2)
        calling = state.shutdown_thread
        if calling is not None and calling is not owner and calling.is_alive():
            rescued.append('owned_public_shutdown_helper_join_after_hook_release')
            REAL_THREAD.join(calling, 2)
        if state.gateway is not None:
            state.hub.detach_node_gateway()
            REAL_GATEWAY.server_close(state.gateway)
        if state.console is not None:
            LeadConsole.server_close(state.console)
        observer.join(1)
        _save(tmp_path, 'fixture-rescue.json', {'rescued_resources': rescued,
            'serve_Thread_alive_after': bool(state.thread and state.thread.is_alive()),
            'shutdown_helper_alive_after': bool(calling is not None and calling is not owner and calling.is_alive()),
            'observer_alive_after': observer.is_alive(), 'implementation_cleanup_credit': False})
    assert state.drain is not None and not state.errors and not state.replacement_expired
    assert not state.drain['fixture_release_already_sent'] and not state.drain['shutdown_returned_before_fixture_release']
    assert state.drain['serve_Thread_alive'] and all(state.drain['hook_fact'][key] for key in
        ('direct_stdlib_caller', 'exact_gateway_self', 'exact_owned_Thread'))
    assert state.drain['CLI_returned_before_fixture_release'], 'HOST_REVIEW_PUBLIC_SHUTDOWN_CALLER_WAIT_UNBOUNDED'
    assert state.drain['CLI_exit'] == 1 and state.main_error is None
    assert state.drain['original_gateway_socket']['closed'] and state.drain['original_console_socket']['closed']
    assert [item['operation'] for item in state.drain['close_attempts'] if item['phase'] == 'CLI'] == ['gateway.close', 'console.close']
    assert state.drain['later_hook_owner_preserved'] and not state.drain['public_listener']['effective_ready']
    # In this deliberately held stdlib call, a finite helper must still be
    # alive at return. This is a remaining-resource diagnostic, not clean exit.
    assert not state.drain['shutdown_called_in_CLI_owner'] and state.drain['shutdown_call_Thread_daemon']
    assert state.drain['shutdown_call_Thread_alive']
    assert len(state.drain['owned_public_join_calls']) == 1
    join = state.drain['owned_public_join_calls'][0]
    assert join['timeout'] == 2 and join['actual_serve_Thread_alive']
    assert join['seconds_after_shutdown_call'] <= 2.3, 'HOST_REVIEW_SHUTDOWN_OBSERVED_WAIT_EXCEEDED_TWO_SECONDS'
    shutdown_errors = [item for item in records if item.get('operation') == 'gateway.shutdown']
    assert len(shutdown_errors) == 1 and shutdown_errors[0]['error']['type'] == 'TimeoutError'
    assert shutdown_errors[0]['error']['message'] == 'owned gateway shutdown timed out; completion not observed'
    assert any(item.get('operation') == 'gateway.thread.join' and item.get('error', {}).get('type') == 'RuntimeError'
               and item['error']['message'] == 'owned gateway Thread did not finish' for item in records)
    assert not state.thread.is_alive() and not state.shutdown_thread.is_alive()
    assert 'Traceback' not in captured.err and CLOCKS == (time.time, time.monotonic, time.perf_counter)


def test_source04_real_pre_started_window_is_bounded_and_late_loop_error_is_owned_diagnostic(
        tmp_path, monkeypatch, capsys):
    """Fixture-only CPython bootstrap gate; no global signal/excepthook patch."""
    thread_source = Path(threading.__file__).resolve()
    tree = ast.parse(thread_source.read_bytes())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Thread')
    start_ast = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'start')
    waits = [node for node in ast.walk(start_ast) if isinstance(node, ast.Call)
             and ast.unparse(node.func) == 'self._started.wait']
    assert sys.implementation.name == 'cpython' and len(waits) == 1, 'FIXTURE_PINNED_CPYTHON_START_ABI'
    wait_line = waits[0].lineno
    _input(tmp_path, 'SOURCE-04', public_entry='CLI.main(hub)',
        fixture_only_private_seam='subclass _bootstrap_inner before calling original',
        stock_start_wait_line=wait_line, stock_threading_path=str(thread_source),
        stock_threading_sha256=hashlib.sha256(thread_source.read_bytes()).hexdigest(),
        stdlib_version=sys.version, signal_used=False, global_excepthook_changed=False,
        observed_start_window_policy_seconds=2.0, expected_exit=1,
        late_public_fileno_fault='ValueError containing synthetic relative private path')
    state = SimpleNamespace(hub=None, console=None, gateway=None, thread=None,
        console_socket=None, gateway_socket=None, bootstrap_arrived=threading.Event(),
        release_bootstrap=threading.Event(), bootstrap_returned=threading.Event(),
        start_interrupted=threading.Event(), main_done=threading.Event(), run_entered=threading.Event(),
        start_fact=None, start_at=None, unresolved=None, serve_events=[], joins=[], shutdowns=[],
        errors=[], expiry=False, exit_code=None, main_error=None, phase='CLI')
    previous_trace = sys.gettrace()
    previous_excepthook = threading.excepthook
    previous_bootstrap = REAL_THREAD._bootstrap_inner

    class CaptureConsole(LeadConsole):
        def __init__(self, hub, *, port):
            super().__init__(hub, port=port)
            state.hub, state.console, state.console_socket = hub, self, self.socket

        def serve_forever(self, poll_interval=.5):
            raise AssertionError('FIXTURE_CONSOLE_SERVE_MUST_NOT_RUN_AFTER_START_INTERRUPT')

    class CaptureGateway(REAL_GATEWAY):
        def __init__(self, hub, *, port=0):
            super().__init__(hub, port=port)
            state.gateway, state.gateway_socket = self, self.socket
            assert self.serve_forever.__func__ is REAL_SERVE

        def fileno(self):
            value = super().fileno()
            if value < 0 and state.release_bootstrap.is_set():
                # The actual closed descriptor is observed first. Inject text
                # only at this public resource seam inside the real stdlib
                # selector registration; no fake loop success or error flag.
                raise ValueError('open proj/late-private.txt failed')
            return value

        def shutdown(self):
            state.shutdowns.append({'phase': state.phase, 'run_entered': state.run_entered.is_set()})
            raise AssertionError('FIXTURE_UNENTERED_LOOP_SHUTDOWN_EXCLUDED')

    class BootstrapThread(REAL_THREAD):
        def _bootstrap_inner(self):
            # Exactly this subclass instance. No global _bootstrap_inner edit,
            # no _started/_handle read or patch. The actual OS Thread has
            # reached this before the unchanged original _started.set().
            state.bootstrap_arrived.set()
            if not state.release_bootstrap.wait(8):
                state.expiry = True
                state.errors.append('FIXTURE_BOOTSTRAP_RELEASE_BOUND')
            try:
                return super()._bootstrap_inner()
            finally:
                state.bootstrap_returned.set()

        def run(self):
            state.run_entered.set()
            old_trace = sys.gettrace()

            def trace_loop(frame, event, arg):
                if frame.f_code is not REAL_SERVE.__code__:
                    return None
                if event == 'call':
                    state.serve_events.append({'event': 'real_stdlib_serve_call',
                        'exact_gateway_self': frame.f_locals.get('self') is state.gateway,
                        'original_socket_fileno': state.gateway_socket.fileno(),
                        'frame_or_locals_retained': False})
                elif event == 'exception':
                    kind, exc, _ = arg
                    state.serve_events.append({'event': 'real_stdlib_serve_exception',
                        'type': kind.__name__, 'message': str(exc), 'frame_or_locals_retained': False})
                return trace_loop

            sys.settrace(trace_loop)  # This fixture-owned Thread only; observe, never catch.
            try:
                return super().run()  # Error propagates to existing owned target/default hook.
            finally:
                sys.settrace(old_trace)

        def join(self, timeout=None):
            state.joins.append({'phase': state.phase, 'actual_run_entered': state.run_entered.is_set(),
                                'timeout': timeout})
            if not state.run_entered.is_set():
                raise AssertionError('FIXTURE_BLIND_JOIN_PRE_STARTED_THREAD_EXCLUDED')
            return super().join(timeout)

    def construct_thread(group=None, target=None, name=None, args=(), kwargs=None,
                         *, daemon=None, context=None):
        cls = BootstrapThread if name == 'techlead-node-gateway' else REAL_THREAD
        options = dict(kwargs or {})
        if cls is BootstrapThread and getattr(target, '__self__', None) is state.gateway:
            assert target.__func__ is REAL_SERVE
            options['poll_interval'] = .01
        result = cls(group=group, target=target, name=name, args=args,
                     kwargs=options, daemon=daemon, **({'context': context} if context is not None else {}))
        if cls is BootstrapThread:
            assert state.thread is None
            state.thread = result
        return result

    def start_interrupt_trace(frame, event, arg):
        if frame.f_code is not REAL_THREAD.start.__code__:
            return None
        if (event == 'line' and frame.f_lineno == wait_line
                and frame.f_locals.get('self') is state.thread and not state.start_interrupted.is_set()):
            assert state.bootstrap_arrived.wait(1), 'FIXTURE_ACTUAL_OS_BOOTSTRAP_NOT_REACHED'
            state.start_at = time.monotonic()
            state.start_fact = {'at': state.start_at, 'stock_start_wait_line': wait_line,
                'exact_Thread_id': id(state.thread), 'actual_subclass_bootstrap_arrived': True,
                'public_is_alive': state.thread.is_alive(), 'public_ident': state.thread.ident,
                'actual_run_entered': state.run_entered.is_set(),
                'original_socket': _socket(state.gateway_socket), 'frame_or_locals_retained': False}
            _save(tmp_path, 'actual-start-before-injected-interrupt.json', state.start_fact)
            state.start_interrupted.set()
            raise KeyboardInterrupt('FIXTURE_KBI_AT_REAL_STOCK_START_WAIT')
        return start_interrupt_trace

    proxy = SimpleNamespace(**vars(threading)); proxy.Thread = construct_thread
    monkeypatch.setattr(lead_cli, 'LeadConsole', CaptureConsole)
    monkeypatch.setattr(lead_cli, 'threading', proxy)
    monkeypatch.setattr(node_gateway, 'NodeGateway', CaptureGateway)

    def observe_then_release():
        try:
            if not state.start_interrupted.wait(3):
                state.errors.append('FIXTURE_ACTUAL_START_INTERRUPT_NOT_REACHED'); return
            returned = state.main_done.wait(2.3)
            state.unresolved = {'at': time.monotonic(), 'CLI_returned_before_bootstrap_release': returned,
                'CLI_exit': state.exit_code, 'elapsed_since_actual_start_interrupt': time.monotonic() - state.start_at,
                'actual_subclass_bootstrap_arrived': state.bootstrap_arrived.is_set(),
                'bootstrap_original_not_released': not state.release_bootstrap.is_set(),
                'public_is_alive': state.thread.is_alive(), 'public_ident': state.thread.ident,
                'actual_run_entered': state.run_entered.is_set(),
                'original_gateway_socket': _socket(state.gateway_socket),
                'original_console_socket': _socket(state.console_socket),
                'listener': _listener(state.hub), 'CLI_join_attempts': copy.deepcopy(state.joins),
                'CLI_shutdown_attempts': copy.deepcopy(state.shutdowns)}
            _save(tmp_path, 'pre-started-before-fixture-bootstrap-release.json', state.unresolved)
        except BaseException as exc:
            state.errors.append('OBSERVER_' + type(exc).__name__)
        finally:
            state.release_bootstrap.set()  # The sole owned bootstrap rescue signal.

    observer = REAL_THREAD(target=observe_then_release, name='fixture-pre-started-observer', daemon=True)
    observer.start()
    sys.settrace(start_interrupt_trace)
    try:
        state.exit_code = lead_cli.main(['hub', '--directory', str(tmp_path / 'empty-hub'),
                                       '--port', '0', '--node-gateway-port', '0'])
    except BaseException as exc:
        state.main_error = {'type': type(exc).__name__}
    finally:
        sys.settrace(previous_trace)
        state.main_done.set()
        observer.join(4)
        state.phase = 'FIXTURE_RESCUE'
        state.release_bootstrap.set()
        actual_bootstrap_done = state.bootstrap_returned.wait(2)
        if state.thread is not None and state.run_entered.is_set():
            REAL_THREAD.join(state.thread, 2)  # Positive actual run/termination, never blind pre-start join.
        _save(tmp_path, 'late-owned-loop-after-bootstrap-release.json', {
            'actual_run_entered': state.run_entered.is_set(), 'bootstrap_returned': actual_bootstrap_done,
            'real_serve_events': state.serve_events[:],
            'owned_Thread_alive_after': bool(state.thread and state.thread.is_alive()),
            'main_error': state.main_error, 'observer_alive': observer.is_alive(),
            'fixture_errors': state.errors[:], 'fixture_expired': state.expiry,
            'global_excepthook_unchanged': threading.excepthook is previous_excepthook,
            'global_bootstrap_inner_unchanged': REAL_THREAD._bootstrap_inner is previous_bootstrap,
            'rescued_resources': ['owned_pre_started_bootstrap_release_then_known_termination_join'],
            'implementation_cleanup_credit': False})
        captured = capsys.readouterr()
        records = _cli_text(tmp_path, captured, state.console)
        if state.gateway is not None:
            state.hub.detach_node_gateway()
            REAL_GATEWAY.server_close(state.gateway)
        if state.console is not None:
            LeadConsole.server_close(state.console)
        if state.hub is not None:
            state.hub.close()
    assert state.start_fact is not None and state.unresolved is not None and not state.errors
    assert state.start_fact['actual_subclass_bootstrap_arrived'] and state.start_fact['public_is_alive'] is False
    assert state.start_fact['public_ident'] is None and state.start_fact['actual_run_entered'] is False
    assert state.unresolved['bootstrap_original_not_released'] and not state.unresolved['actual_run_entered']
    assert state.unresolved['public_is_alive'] is False and state.unresolved['public_ident'] is None
    assert state.unresolved['CLI_returned_before_bootstrap_release'] and state.main_error is None
    assert state.unresolved['CLI_exit'] == 1, 'HOST_REVIEW_PRE_STARTED_WINDOW_REPORTED_CLEAN_INTERRUPT_EXIT'
    assert 1.8 <= state.unresolved['elapsed_since_actual_start_interrupt'] <= 2.3, 'HOST_REVIEW_OWNED_START_OBSERVATION_WINDOW'
    assert state.unresolved['original_gateway_socket']['closed'] and state.unresolved['original_console_socket']['closed']
    assert not state.unresolved['CLI_join_attempts'] and not state.unresolved['CLI_shutdown_attempts']
    assert state.unresolved['listener']['gateway'] is None and state.unresolved['listener']['effective_ready'] is False
    assert state.run_entered.is_set() and actual_bootstrap_done and not state.thread.is_alive()
    assert any(item['event'] == 'real_stdlib_serve_call' and item['exact_gateway_self']
               and item['original_socket_fileno'] == -1 for item in state.serve_events)
    assert any(item['event'] == 'real_stdlib_serve_exception' and item['type'] == 'ValueError'
               for item in state.serve_events)
    unresolved_errors = [item for item in records if item.get('operation') == 'gateway.entry.observe']
    assert len(unresolved_errors) == 1 and unresolved_errors[0]['error'] == {
        'type': 'TimeoutError', 'message': 'owned gateway start outcome unresolved after 2 seconds'}
    late_errors = [item for item in records if item.get('operation') == 'gateway.serve']
    assert len(late_errors) == 1 and late_errors[0]['error'] == {
        'type': 'ValueError', 'message': 'host lifecycle failure during gateway.serve'}
    assert 'late-private.txt' not in captured.err and 'proj/' not in captured.err
    assert 'Traceback' not in captured.err and 'Exception in thread' not in captured.err
    assert threading.excepthook is previous_excepthook and REAL_THREAD._bootstrap_inner is previous_bootstrap
    assert CLOCKS == (time.time, time.monotonic, time.perf_counter)
