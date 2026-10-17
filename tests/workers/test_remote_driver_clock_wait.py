"""Frozen final-clock races: real canonical claims, retained local fixtures only.

Clock is the injected invocation timer, not a node lease renewal. Its last
sample may change persisted currency, so no sleep/relay follows a lost claim.
Original 116 driver tests and the retained waiting-two oracle stay unchanged.
"""
import json

import pytest

import test_remote_driver as frozen


class FinalClock:
    """Change currency on the second invocation-clock sample after controls."""

    def __init__(self, env, phase, change):
        self.env, self.phase, self.change = env, phase, change
        self.samples, self.fired = 0, False
        self.before_change = None

    def controls(self):
        self.samples = 0
        return []

    def __call__(self):
        view = self.env.claims.get('run-worker')
        if view is not None and view['status'] == self.phase and not self.fired:
            self.samples += 1
            if self.samples == 2:
                self.fired = True
                self.before_change = view
                self.change()
        return self.env.clock.tick


@pytest.mark.parametrize('loss', ['node-expiry', 'epoch', 'core-owner'])
def test_final_clock_currency_loss_returns_unknown_without_an_extra_sleep(tmp_path, monkeypatch, loss):
    env = frozen.env.__wrapped__(tmp_path, monkeypatch)
    before_core = frozen.core(env)
    before_source = frozen.artifacts.full_tree_manifest(env.request.cwd)
    before_uploads = frozen.artifacts.full_tree_manifest(env.claims.artifact_root)
    offered, relayed, emitted = [], [], []
    original_offer, original_relay = env.claims.offer, env.claims.post_controls

    def offer(*args, **kwargs):
        offered.append(args)
        return original_offer(*args, **kwargs)

    def relay(*args, **kwargs):
        relayed.append(args)
        return original_relay(*args, **kwargs)

    def lose_currency():
        if loss == 'node-expiry':
            env.clock.wall += 31  # Core's 60s lease remains live; node's 30s does not.
        else:
            with env.journal.store._transaction() as db:
                if loss == 'epoch':
                    db.execute("UPDATE remote_offers SET epoch=2 WHERE run_key='run-worker'")
                else:
                    db.execute("UPDATE continuations SET lease_token='fixture-replaced-owner' WHERE id=?",
                               (env.continuation['id'],))

    monkeypatch.setattr(env.claims, 'offer', offer)
    monkeypatch.setattr(env.claims, 'post_controls', relay)
    clock = FinalClock(env, 'CLAIMED', lose_currency)
    d = frozen.driver(env, clock=clock)
    env.clock.steps.append(lambda: frozen.claim(env))
    receipt = d.run(env.request, lambda *args: emitted.append(args), clock.controls)
    assert clock.fired and clock.before_change['epoch'] == 1
    assert env.clock.tick < env.request.timeout, 'the failure is currency loss, not invocation timeout'
    assert receipt.status == 'UNKNOWN' and receipt.error
    assert receipt.requested_model == 'gpt-6.1-sol' and receipt.actual_model is None
    assert env.clock.sleeps == [0.2], 'only the initial offered wait, zero wait after final clock drops currency'
    assert len(offered) == 1 and not relayed and not emitted
    assert d.materialization['status'] == 'UNKNOWN' and not env.candidate.exists()
    assert frozen.artifacts.full_tree_manifest(env.request.cwd) == before_source
    assert frozen.artifacts.full_tree_manifest(env.snapshot) == before_source
    assert frozen.artifacts.full_tree_manifest(env.claims.artifact_root) == before_uploads
    assert (env.snapshot / 'main.txt').read_bytes() == b'original'
    assert (env.snapshot / 'keep.txt').read_bytes() == b'keep'
    assert (frozen.Path(env.request.cwd) / 'main.txt').read_bytes() == b'original'
    assert frozen.core(env) == before_core
    assert env.journal.store.verify_event_chain()['valid'] is True
    view = env.claims.get('run-worker')
    assert view['claim_id'] == clock.before_change['claim_id'] and view['receipt'] is None
    if loss in {'node-expiry', 'core-owner'}:
        assert view['status'] == 'UNKNOWN' and view['epoch'] == 1
    else:
        assert view['epoch'] == 2 and view['status'] == 'CLAIMED'


@pytest.mark.parametrize('phase,expected,sleeps', [('OFFERED', 'ERROR', []), ('CLAIMED', 'UNKNOWN', [0.2])])
def test_final_clock_reaches_total_deadline_no_extra_wait_or_late_interrupt_relay(tmp_path, monkeypatch, phase, expected, sleeps):
    env = frozen.env.__wrapped__(tmp_path, monkeypatch)
    before_core = frozen.core(env)
    before_source = frozen.artifacts.full_tree_manifest(env.request.cwd)
    relayed, withdraws = [], []
    withdraw = env.claims.withdraw

    def expired():
        env.clock.tick = env.request.timeout  # Exact remaining == 0 boundary.

    def controls():
        clock.controls()
        # This command appears only AFTER the invocation deadline; it must not
        # be relayed to a claimed node or treated as native acknowledgement.
        return [{'id': 'late-clock-stop', 'action': 'interrupt', 'text': ''}] if clock.fired else []

    def record_withdraw(*args, **kwargs):
        withdraws.append(args)
        return withdraw(*args, **kwargs)

    monkeypatch.setattr(env.claims, 'withdraw', record_withdraw)
    monkeypatch.setattr(env.claims, 'post_controls', lambda *args: relayed.append(args))
    clock = FinalClock(env, phase, expired)
    d = frozen.driver(env, clock=clock)
    if phase == 'CLAIMED':
        env.clock.steps.append(lambda: frozen.claim(env))
    emitted = []
    receipt = d.run(env.request, lambda *args: emitted.append(args), controls)
    assert clock.fired and receipt.status == expected and receipt.error
    assert env.clock.tick == env.request.timeout and env.clock.sleeps == sleeps
    assert len(withdraws) == 1 and not relayed and not emitted
    view = env.claims.get('run-worker')
    if phase == 'OFFERED':
        assert (view['status'], view['epoch'], view['claim_id']) == ('WITHDRAWN', 0, None)
    else:
        assert view['status'] == 'CLAIMED' and view['epoch'] == 1 and view['claim_id']
    assert view['receipt'] is None and frozen.core(env) == before_core
    assert frozen.artifacts.full_tree_manifest(env.request.cwd) == before_source
    assert frozen.artifacts.full_tree_manifest(env.snapshot) == before_source
    assert not env.candidate.exists() and env.journal.store.verify_event_chain()['valid']
    assert receipt.requested_model == 'gpt-6.1-sol' and receipt.actual_model is None
    assert json.loads(json.dumps(receipt.as_dict()))['status'] == expected
