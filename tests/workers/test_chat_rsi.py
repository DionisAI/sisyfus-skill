"""Conversational RSI configuration: controller receipts, not native execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from sisyfus.workers.chat_rsi import instruction, planning_text, prepare, validate
from sisyfus.workers.lead_chat import ChatSessions
from sisyfus.workers.lead_contracts import load_lead_spec
from sisyfus.workers.protocol import digest
from test_lead_chat import (attach, chat_factory, chats, driver, finish, hub,
                           offline_only, server, spec, spec_file, stored)


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / "operator catalog"
    root.mkdir()
    # Referenced files deliberately do not exist: configuration must NOT inspect
    # source, checks or held-out task content before a procedure is proposed.
    (root / "manifest.json").write_text(json.dumps({
        "schema": "sisyfus.lead_trials.v1",
        "search": [{"id": "search", "spec": "search.json"}],
        "holdout": [{"id": "holdout", "spec": "SECRET-HOLDOUT.json"}],
    }))
    return root


@pytest.mark.parametrize("text", ["开启 RSI", "请开启 RSI", "启用RSI", "运行 RSI", "RSI 只评估，不自动晋升", "请先开启 RSI", "给这个项目打开 RSI"])
def test_explicit_conversation_configuration(text):
    assert instruction(text)["enabled"] is True


@pytest.mark.parametrize("text", ["什么是 RSI？", "能否开启 RSI？", "如何开启 RSI", "先不要开启 RSI", "如果开启 RSI 会怎样", "例如：开启 RSI", "RSI 已开启", "实现一个开启 RSI 的按钮", "RSI 开启后会怎样", "开启 RSI 的按钮在哪里"])
def test_discussion_never_grants_configuration(text):
    assert instruction(text) is None


def test_only_a_catalog_path_is_used():
    assert instruction('开启 RSI，评估集目录为 `/private/tmp/with spaces`')["evaluation_root"] == '/private/tmp/with spaces'
    assert instruction('开启 RSI，工程目录 /project，评估集目录 /catalog')["evaluation_root"] == '/catalog'
    assert instruction('开启 RSI，评估集目录 /one 或 /two')["issue"]


def test_followup_answers_only_an_existing_controller_gap():
    pending = {'status': 'NEEDS_INPUT', 'configuration': {'enabled': True}}
    assert instruction('评估集目录为 /catalog') is None
    assert instruction('评估集目录为 /catalog', pending)['evaluation_root'] == '/catalog'
    assert instruction('`/catalog`', pending)['evaluation_root'] == '/catalog'
    assert instruction('`/catalog`', {'status': 'CONFIGURED', 'configuration': {'enabled': True}}) is None
    assert planning_text('开启 RSI，评估集 `/catalog`。实现 job.py，保留验收。') == '开启 RSI，评估集 [控制器持有的评估集路径]。实现 job.py，保留验收。'


def test_configuration_reads_only_manifest(catalog, tmp_path):
    record = prepare(instruction(f'开启 RSI，评估集目录为 `{catalog}`'), {}, tmp_path / 'hub', '')
    assert record['status'] == 'CONFIGURED'
    assert record['catalog']['search_cases'] == record['catalog']['holdout_cases'] == 1
    assert record['configuration']['evaluation_manifest_hash'] == hashlib.sha256((catalog / 'manifest.json').read_bytes()).hexdigest()
    assert 'SECRET-HOLDOUT' not in json.dumps(record)


def test_missing_catalog_is_concrete_preparation_gap(tmp_path):
    record = prepare(instruction('开启 RSI'), {}, tmp_path / 'hub', '')
    assert record['status'] == 'NEEDS_INPUT'
    assert '评估集' in record['detail']


@pytest.mark.parametrize('bad', [[], {}, {'search': [], 'holdout': []}, {'search': [{'id': 'x', 'spec': 'x.json'}], 'holdout': [{'id': 'x', 'spec': 'y.json'}]}])
def test_invalid_manifest_is_observable(catalog, tmp_path, bad):
    (catalog / 'manifest.json').write_text(json.dumps(bad))
    record = prepare(instruction(f'开启 RSI，评估集目录 `{catalog}`'), {}, tmp_path / 'hub', '')
    assert record['status'] == 'ERROR' and record['error']['type'] == 'ValueError'


def test_chat_manifest_references_files_not_inline_holdout_definitions(catalog, tmp_path):
    manifest = json.loads((catalog / 'manifest.json').read_text())
    manifest['holdout'][0]['spec'] = {'objective': 'PRIVATE-HOLDOUT-CONTENT'}
    (catalog / 'manifest.json').write_text(json.dumps(manifest))
    record = prepare(instruction(f'开启 RSI，评估集目录 `{catalog}`'), {}, tmp_path / 'hub', '')
    assert record['status'] == 'ERROR'
    assert '文件路径引用' in record['error']['message']
    assert 'PRIVATE-HOLDOUT-CONTENT' not in json.dumps(record)


def test_finite_parent_caps_remain_unchanged(catalog, tmp_path):
    base = {'max_calls': 9}
    record = prepare(instruction(f'开启 RSI，评估集目录 `{catalog}`'), base, tmp_path / 'hub', '')
    assert record['status'] == 'NEEDS_INPUT' and 'max_calls' in record['detail']
    assert base == {'max_calls': 9}


@pytest.mark.parametrize('overlap', ['source', 'hub'])
def test_catalog_is_disjoint_from_project_and_control(catalog, overlap):
    root = catalog.parent
    record = prepare(instruction(f'开启 RSI，评估集目录 `{catalog}`'), {}, catalog if overlap == 'hub' else root / 'hub', str(catalog) if overlap == 'source' else '')
    assert record['status'] == 'ERROR'


def test_symlink_catalog_rejected(catalog, tmp_path):
    alias = tmp_path / 'alias'
    alias.symlink_to(catalog, target_is_directory=True)
    assert prepare(instruction(f'开启 RSI，评估集目录 `{alias}`'), {}, tmp_path / 'hub', '')['status'] == 'ERROR'


def test_manifest_drift_fences_execution(catalog, tmp_path):
    record = prepare(instruction(f'开启 RSI，评估集目录 `{catalog}`'), {}, tmp_path / 'hub', '')
    config = record['configuration']
    validate(config, {}, tmp_path / 'hub', '')
    (catalog / 'manifest.json').write_text((catalog / 'manifest.json').read_text() + '\n')
    with pytest.raises(ValueError, match='评估集.*变化'):
        validate(config, {}, tmp_path / 'hub', '')


def unlimited(spec_file):
    value = json.loads(spec_file.read_text())
    for name in ('max_calls', 'max_iterations', 'max_tokens', 'max_cost_usd', 'max_wall_minutes'):
        value[name] = None
    spec_file.write_text(json.dumps(value))


def configure(chats, spec_file, catalog, *, auto=True):
    unlimited(spec_file)
    ident = attach(chats, spec_file)
    suffix = '，通过门槛后自动晋升' if auto else '，只评估，不自动晋升'
    chats.message(ident, f'开启 RSI，评估集目录为 `{catalog}`' + suffix, 'rsi-message-01')
    return ident, finish(chats, ident)


def test_chat_configuration_is_durable_and_not_dispatch(chats, spec_file, catalog, driver, hub):
    before = spec_file.read_bytes()
    ident, result = configure(chats, spec_file, catalog)
    approved_bytes = spec_file.read_bytes()
    assert result['rsi_preparation']['status'] == 'CONFIGURED'
    assert result['rsi_configuration']['evaluation_root'] == str(catalog)
    assert result['readiness']['ready'] is True
    assert any(message.get('kind') == 'rsi' for message in result['messages'])
    assert hub.inventory()['missions'] == []
    assert len(driver.calls) == 1
    assert str(catalog) not in driver.calls[0].prompt
    assert 'SECRET-HOLDOUT' not in driver.calls[0].prompt
    assert 'rsi_preparation' in driver.calls[0].prompt
    assert chats.get(ident)['approval_hash'] == result['approval_hash']
    assert spec_file.read_bytes() == approved_bytes
    assert before  # retained original bytes, no removal


def test_start_preserves_acceptance_and_passes_conversational_rsi_to_controller(chats, spec_file, catalog, hub):
    ident, result = configure(chats, spec_file, catalog, auto=False)
    base = load_lead_spec(stored(chats, ident)['bound_spec'])
    chats.start(ident, True, 'rsi-start-01', result['approval_hash'])
    session = hub._session(chats.get(ident)['mission_id'])
    assert session.mission.spec['rsi']['auto_promote'] is False
    assert session.mission.spec['rsi']['evaluation_root'] == str(catalog)
    assert session.mission.spec['checks'] == base['checks']
    assert session.mission.spec['acceptance_hash'] == base['acceptance_hash']
    assert session.mission.spec['roles'] == base['roles']
    assert session.mission.spec['max_calls'] is None


def test_unprepared_rsi_blocks_start(chats, spec_file, hub):
    unlimited(spec_file)
    ident = attach(chats, spec_file)
    chats.message(ident, '开启 RSI', 'rsi-missing-01')
    result = finish(chats, ident)
    assert result['rsi_preparation']['status'] == 'NEEDS_INPUT'
    assert result['readiness']['ready'] is False
    with pytest.raises(ValueError):
        chats.start(ident, True, 'rsi-missing-start', result['approval_hash'])
    assert hub.inventory()['missions'] == []


def test_changed_manifest_fences_start_before_reservation(chats, spec_file, catalog, hub):
    ident, result = configure(chats, spec_file, catalog)
    (catalog / 'manifest.json').write_text((catalog / 'manifest.json').read_text() + '\n')
    with pytest.raises(ValueError, match='评估集.*变化'):
        chats.start(ident, True, 'rsi-drift-start', result['approval_hash'])
    assert 'rsi-drift-start' not in stored(chats, ident)['requests']
    assert hub.inventory()['missions'] == []


def test_disable_withdraws_old_confirmation(chats, spec_file, catalog, hub):
    ident, result = configure(chats, spec_file, catalog)
    old_hash = result['approval_hash']
    chats.message(ident, '关闭 RSI', 'rsi-disable-01')
    result = finish(chats, ident)
    assert result['rsi_configuration']['enabled'] is False
    assert result['approval_hash'] != old_hash
    with pytest.raises(RuntimeError):
        chats.start(ident, True, 'rsi-old-approval', old_hash)
    assert hub.inventory()['missions'] == []


def test_configuration_receipt_survives_restart_and_duplicate_message(chats, spec_file, catalog, chat_factory, driver):
    ident, result = configure(chats, spec_file, catalog)
    count = len(result['messages'])
    message = next(m['text'] for m in result['messages'] if m['id'] == 'rsi-message-01')
    chats.close()
    resumed = chat_factory()
    duplicate = resumed.message(ident, message, 'rsi-message-01')
    assert duplicate['rsi_configuration'] == result['rsi_configuration']
    assert len(duplicate['messages']) == count and len(driver.calls) == 1
