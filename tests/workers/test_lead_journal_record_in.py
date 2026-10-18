"""Frozen caller-owned record transaction contract; isolated database fixtures only."""
from contextlib import contextmanager
import inspect
import json
import sqlite3

import pytest

from sisyfus.autonomy.models import canonical_json
from sisyfus.autonomy.policy import IdempotencyConflictError
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.lead_journal import LeadJournal


STAMP = "2026-10-06T12:00:00Z"
PAYLOAD = {"state": "REQUESTED", "revision": 2, "notes": ["fixture"]}


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr("sisyfus.workers.lead_journal.utc_now", lambda: STAMP)
    return LeadJournal(AutonomyStore(tmp_path / "autonomy.sqlite3"))


def saved(key="current", data=None):
    return {"key": key, "created_at": STAMP, "data": PAYLOAD if data is None else data}


def row(db, category="preparation", key="current"):
    result = db.execute("SELECT value FROM metadata WHERE key=?",
                        ("techlead:" + category + ":" + key,)).fetchone()
    return json.loads(result[0]) if result else None


def projection(journal):
    return journal.records("preparation"), journal.events(), journal.store.verify_event_chain()


class CallerConnection:
    """Forward SQL but forbid transaction ownership or schema changes."""

    def __init__(self, db, fail_at=None):
        self.db, self.fail_at = db, fail_at

    def execute(self, sql, *args):
        verb = sql.lstrip().split()[0].upper()
        assert verb not in {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "CREATE", "DROP"}
        if self.fail_at and sql.lstrip().startswith(self.fail_at):
            raise sqlite3.OperationalError("fixed record SQL failure")
        return self.db.execute(sql, *args)

    def commit(self):
        raise AssertionError("caller owns commit")

    def rollback(self):
        raise AssertionError("caller owns rollback")

    def close(self):
        raise AssertionError("caller owns connection lifetime")


def test_original_record_wire_shape_getter_event_and_hash(journal):
    result = journal.record("preparation", "current", PAYLOAD)
    assert result == saved()
    assert journal.get("preparation", "current") == PAYLOAD
    assert journal.records("preparation") == [saved()]
    event = journal.events()[-1]
    assert event["type"] == "WORKER_LEAD_PREPARATION"
    assert event["run_key"] == "current" and event["data"] == saved()
    assert journal.store.verify_event_chain()["valid"]


def test_original_redaction_and_redacted_equivalent_replay_stay_unchanged(journal):
    result = journal.record("preparation", "current", {"authorization": "FIXTURE_ALPHA"})
    before = projection(journal)
    assert result == saved(data={"authorization": "[REDACTED]"})
    assert journal.record("preparation", "current", {"authorization": "FIXTURE_BETA"}) == result
    assert projection(journal) == before


def test_record_in_public_signature_and_exact_wire_shape(journal):
    assert list(inspect.signature(LeadJournal.record_in).parameters) == ["self", "db", "category", "key", "data"]
    with journal.store._transaction() as db:
        assert journal.record_in(db, "preparation", "current", PAYLOAD) == saved()
        assert row(db) == saved()
        event = db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        assert event["event_type"] == "WORKER_LEAD_PREPARATION"
        assert event["entity_type"] == "native_worker" and event["entity_id"] == "current"
        assert event["actor"] == "native-worker" and event["continuation_id"] is None
        assert event["data_json"] == canonical_json(saved())
    assert journal.store.verify_event_chain()["valid"]


def test_record_in_never_opens_a_nested_transaction(journal, monkeypatch):
    def nested_forbidden(*args, **kwargs):
        raise AssertionError("nested transaction")

    with journal.store._transaction() as db:
        with monkeypatch.context() as patch:
            patch.setattr(journal.store, "_transaction", nested_forbidden)
            assert journal.record_in(db, "preparation", "current", PAYLOAD) == saved()
            assert row(db) == saved()
    assert journal.get("preparation", "current") == PAYLOAD


def test_record_in_passes_the_exact_caller_connection_to_event(journal, monkeypatch):
    original, observed = journal._event, []

    def event(db, kind, key, data, *args, **kwargs):
        observed.append(db)
        assert row(db) == saved()
        db.execute("INSERT INTO metadata VALUES('fixture:callback','same-transaction')")
        original(db, kind, key, data, *args, **kwargs)

    monkeypatch.setattr(journal, "_event", event)
    with journal.store._transaction() as db:
        supplied = CallerConnection(db)
        assert journal.record_in(supplied, "preparation", "current", PAYLOAD) == saved()
        assert observed == [supplied] and db.in_transaction
        assert db.execute("SELECT value FROM metadata WHERE key='fixture:callback'").fetchone()[0] == "same-transaction"
    assert journal.store.verify_event_chain()["valid"]


def test_uncommitted_record_and_event_are_not_visible_to_an_independent_reader(journal):
    with journal.store._transaction() as db:
        before_count = db.execute("SELECT count(*) FROM events").fetchone()[0]
        journal.record_in(db, "preparation", "current", PAYLOAD)
        with journal.store._transaction(immediate=False) as reader:
            assert row(reader) is None
            assert reader.execute("SELECT count(*) FROM events").fetchone()[0] == before_count
        assert db.in_transaction
    assert journal.get("preparation", "current") == PAYLOAD


def test_caller_abort_rolls_back_record_event_and_other_writes(journal):
    before = projection(journal)
    with pytest.raises(RuntimeError, match="caller abort"):
        with journal.store._transaction() as db:
            db.execute("INSERT INTO metadata VALUES('fixture:caller','retained-by-owner')")
            journal.record_in(db, "preparation", "current", PAYLOAD)
            raise RuntimeError("caller abort")
    assert projection(journal) == before
    with journal.store._transaction(immediate=False) as db:
        assert db.execute("SELECT 1 FROM metadata WHERE key='fixture:caller'").fetchone() is None


def test_event_callback_failure_is_exposed_and_owner_rolls_back_every_write(journal, monkeypatch):
    before, original = projection(journal), journal._event
    failure = RuntimeError("fixed callback failure")

    def event(db, *args, **kwargs):
        original(db, *args, **kwargs)
        db.execute("INSERT INTO metadata VALUES('fixture:callback','rollback')")
        raise failure

    monkeypatch.setattr(journal, "_event", event)
    with pytest.raises(RuntimeError) as exc:
        with journal.store._transaction() as db:
            journal.record_in(db, "preparation", "current", PAYLOAD)
    assert exc.value is failure and projection(journal) == before
    with journal.store._transaction(immediate=False) as db:
        assert db.execute("SELECT 1 FROM metadata WHERE key='fixture:callback'").fetchone() is None


@pytest.mark.parametrize("fail_at", ["SELECT value FROM metadata", "INSERT INTO metadata", "INSERT INTO events"])
def test_sql_failure_preserves_exception_and_rolls_back_hash_chain(journal, fail_at):
    before = projection(journal)
    with pytest.raises(sqlite3.OperationalError, match="fixed record SQL failure"):
        with journal.store._transaction() as db:
            journal.record_in(CallerConnection(db, fail_at), "preparation", "current", PAYLOAD)
    assert projection(journal) == before


def test_idempotent_record_in_same_and_later_transactions_keeps_timestamp_and_event(journal, monkeypatch):
    with journal.store._transaction() as db:
        first = journal.record_in(db, "preparation", "current", PAYLOAD)
        count = db.execute("SELECT count(*) FROM events").fetchone()[0]
        monkeypatch.setattr("sisyfus.workers.lead_journal.utc_now", lambda: "2026-10-07T12:00:00Z")
        assert journal.record_in(db, "preparation", "current", dict(PAYLOAD)) == first
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == count
    before = projection(journal)
    with journal.store._transaction() as db:
        assert journal.record_in(db, "preparation", "current", dict(PAYLOAD)) == first == saved()
    assert projection(journal) == before


def test_conflicting_record_in_exposes_original_error_and_keeps_original_receipt(journal):
    journal.record("preparation", "current", PAYLOAD)
    before = projection(journal)
    with pytest.raises(IdempotencyConflictError, match="^conflicting preparation record: current$"):
        with journal.store._transaction() as db:
            journal.record_in(db, "preparation", "current", {"state": "CHANGED"})
    assert projection(journal) == before


def test_record_in_redacts_nested_synthetic_data_and_preserves_legacy_equivalence(journal):
    expected = {"authorization": "[REDACTED]", "text": "Bearer [REDACTED]",
                "nested": [{"api_key": "[REDACTED]", "synthetic_token": "[REDACTED]", "value": 3}]}
    with journal.store._transaction() as db:
        first = journal.record_in(db, "preparation", "current", {
            "authorization": "FIXTURE_ALPHA", "text": "Bearer FIXTURE_ALPHA_ONLY",
            "nested": [{"api_key": "FAKE_ONLY", "synthetic_token": "FAKE_ONLY", "value": 3}]})
        count = db.execute("SELECT count(*) FROM events").fetchone()[0]
        assert first == saved(data=expected)
        assert journal.record_in(db, "preparation", "current", {
            "authorization": "FIXTURE_BETA", "text": "Bearer FIXTURE_BETA_ONLY",
            "nested": [{"api_key": "OTHER_FAKE", "synthetic_token": "OTHER_FAKE", "value": 3}]}) == first
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == count
    assert journal.get("preparation", "current") == expected


def test_record_in_does_not_alias_mutable_input_or_persisted_return(journal):
    payload = {"notes": ["original"]}
    with journal.store._transaction() as db:
        result = journal.record_in(db, "preparation", "current", payload)
        payload["notes"].append("input-mutation")
        result["data"]["notes"].append("return-mutation")
        assert row(db) == saved(data={"notes": ["original"]})
    assert journal.get("preparation", "current") == {"notes": ["original"]}


def test_record_does_not_enter_native_acceptance_callback(journal):
    def forbidden(*args, **kwargs):
        raise AssertionError("record is not native acceptance")

    journal.after_event = forbidden
    journal.record("preparation", "original", PAYLOAD)
    with journal.store._transaction() as db:
        journal.record_in(db, "preparation", "current", PAYLOAD)
    assert journal.store.verify_event_chain()["valid"]


def test_record_wrapper_opens_one_transaction_and_delegates_exact_arguments(journal, monkeypatch):
    transaction, seen = journal.store._transaction, []

    @contextmanager
    def owned(*args, **kwargs):
        seen.append((args, kwargs))
        with transaction(*args, **kwargs) as db:
            yield db

    def delegated(db, category, key, data):
        assert db.in_transaction and category == "preparation" and key == "current" and data is PAYLOAD
        db.execute("INSERT INTO metadata VALUES('fixture:wrapper','delegated')")
        return saved()

    with monkeypatch.context() as patch:
        patch.setattr(journal.store, "_transaction", owned)
        patch.setattr(journal, "record_in", delegated)
        assert journal.record("preparation", "current", PAYLOAD) == saved()
        assert seen == [((), {})]
    with transaction(immediate=False) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='fixture:wrapper'").fetchone()[0] == "delegated"


def test_history_and_new_requested_record_commit_as_one_owner_transaction(journal):
    history = {"state": "FAILED", "revision": 1}
    with journal.store._transaction() as db:
        journal.record_in(db, "preparation_history", "prior", history)
        journal.record_in(db, "preparation", "current", PAYLOAD)
    assert journal.get("preparation_history", "prior") == history
    assert journal.get("preparation", "current") == PAYLOAD
    events = journal.events()[-2:]
    assert [e["type"] for e in events] == ["WORKER_LEAD_PREPARATION_HISTORY", "WORKER_LEAD_PREPARATION"]
    assert journal.store.verify_event_chain()["valid"]


def test_history_and_requested_second_event_failure_roll_back_together(journal, monkeypatch):
    before, original = projection(journal), journal._event

    def event(db, kind, *args, **kwargs):
        original(db, kind, *args, **kwargs)
        if kind == "lead_preparation":
            raise RuntimeError("requested append failure")

    monkeypatch.setattr(journal, "_event", event)
    with pytest.raises(RuntimeError, match="requested append failure"):
        with journal.store._transaction() as db:
            journal.record_in(db, "preparation_history", "prior", {"state": "FAILED"})
            journal.record_in(db, "preparation", "current", PAYLOAD)
    assert journal.get("preparation_history", "prior") is None
    assert projection(journal) == before


def test_record_wrapper_callback_failure_remains_atomic(journal, monkeypatch):
    before, original = projection(journal), journal._event

    def event(db, *args, **kwargs):
        original(db, *args, **kwargs)
        raise RuntimeError("wrapper event failure")

    monkeypatch.setattr(journal, "_event", event)
    with pytest.raises(RuntimeError, match="wrapper event failure"):
        journal.record("preparation", "current", PAYLOAD)
    assert projection(journal) == before
