"""Durable conversation drafts, never task truth or an automatic dispatch path.

Native Opus can read a selected project and propose prose. Only operator-supplied,
hash-validated checks bind a mission. Draft proposals cannot invent executable
checks; confirmed execution delegates to MissionHub/LeadMission unchanged.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .claude_code import ClaudeCodeDriver
from .lead_contracts import load_lead_spec
from .lead_mission import strict_json
from .protocol import Receipt, Request, digest, redact

MODEL = 'claude-opus-5-5'
_ID = re.compile(r'c_[a-f0-9]{32}\Z')
_REQUEST = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_-]{7,99}\Z')


def durable_flush(fd: int) -> None:
    os.fsync(fd)
    if sys.platform == 'darwin':
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)


def flush_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        durable_flush(fd)
    finally:
        os.close(fd)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def error(exc: Exception) -> dict[str, str]:
    return {'type': type(exc).__name__, 'message': str(redact(str(exc)))[:2000]}


def proposal(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - {'reply', 'proposal'}:
        raise ValueError('Opus reply must contain only reply and proposal')
    if not isinstance(raw.get('reply'), str) or not 1 <= len(raw['reply']) <= 20000:
        raise ValueError('Opus reply needs nonempty bounded text')
    value = raw.get('proposal')
    if value is None:
        return raw
    if not isinstance(value, dict) or set(value) != {'objective', 'architecture', 'deliverables', 'constraints', 'tasks'}:
        raise ValueError('proposal needs objective, architecture, deliverables, constraints and tasks')
    for field in ('objective', 'architecture'):
        if not isinstance(value[field], str) or not 1 <= len(value[field]) <= 20000:
            raise ValueError('proposal ' + field + ' needs bounded text')
    for field in ('deliverables', 'constraints'):
        if not isinstance(value[field], list) or len(value[field]) > 32 or any(not isinstance(x, str) or not 1 <= len(x) <= 2000 for x in value[field]):
            raise ValueError('proposal ' + field + ' needs bounded text entries')
    if not isinstance(value['tasks'], list) or not 1 <= len(value['tasks']) <= 32:
        raise ValueError('proposal needs 1..32 task outlines')
    for task in value['tasks']:
        if not isinstance(task, dict) or set(task) != {'title', 'acceptance', 'depends_on'}:
            raise ValueError('task outline needs title, acceptance and depends_on')
        if any(not isinstance(task[x], str) or not 1 <= len(task[x]) <= 4000 for x in ('title', 'acceptance')):
            raise ValueError('task outline needs bounded title/acceptance')
        if not isinstance(task['depends_on'], list) or any(not isinstance(x, str) or len(x) > 200 for x in task['depends_on']):
            raise ValueError('outline dependencies need text entries')
    return raw


class ChatSessions:
    def __init__(self, hub: Any, *, driver: Any = None):
        self.hub = hub
        self.root = hub.directory / '.chats'
        if self.root.is_symlink():
            raise ValueError('chat directory must not be a symlink')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        flush_directory(self.root.parent)
        self.owner = open(self.root / '.owner.lock', 'a+')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise RuntimeError('conversation directory already has an active owner')
        self.driver = driver or ClaudeCodeDriver()
        self.lock = threading.RLock()
        self.threads: dict[str, threading.Thread] = {}
        self.closed = False
        self.issues: dict[str, dict[str, Any]] = {}
        # A lost process never turns an unreceipted request into a fresh call.
        for path in self.root.glob('c_*/draft.json'):
            try:
                state = self._read(path.parent.name)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.issues[path.parent.name] = {'id': path.parent.name, 'error': error(exc)}
                continue
            if state['status'] in {'RUNNING', 'STARTING'}:
                state.update(status='UNKNOWN', error={'type': 'InterruptedRequest', 'message': '上次请求的结果待核对；已保留记录，当前对话暂停派发。请查看诊断或新建对话。'})
                self._save(state)

    def _path(self, ident: str) -> Path:
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            raise ValueError('invalid chat id')
        path = self.root / ident
        if path.is_symlink() or path.resolve().parent != self.root.resolve():
            raise ValueError('chat must be a fixed non-symlink child')
        return path

    def _read(self, ident: str) -> dict[str, Any]:
        path = self._path(ident) / 'draft.json'
        if path.is_symlink():
            raise ValueError('draft must be a regular file')
        state = json.loads(path.read_text())
        if not isinstance(state, dict) or not isinstance(state.get('status'), str) or not isinstance(state.get('updated_at'), str):
            raise ValueError('draft must be an object with status and updated_at')
        if state.get('id') != ident:
            raise ValueError('chat identity mismatch')
        if any(not isinstance(state.get(k), str) for k in ('title', 'source', 'spec_path')):
            raise ValueError('draft is missing its text context fields')
        if state['status'] not in {'IDLE', 'RUNNING', 'STARTING', 'UNKNOWN', 'ERROR'}:
            raise ValueError('draft has an invalid conversation status')
        if not isinstance(state.get('requests'), dict) or not isinstance(state.get('messages'), list):
            raise ValueError('draft needs request reservations and message history')
        for message in state['messages']:
            if not isinstance(message, dict) or message.get('role') not in {'user', 'assistant'} or not isinstance(message.get('text'), str):
                raise ValueError('draft contains malformed message history')
        if state.get('bound_spec') is not None and not isinstance(state['bound_spec'], dict):
            raise ValueError('draft bound specification must be an object')
        if state.get('proposal') is not None:
            proposal({'reply': 'draft shape validation', 'proposal': state['proposal']})
        return state

    def _save(self, state: dict[str, Any]) -> None:
        state['updated_at'] = now()
        path = self._path(state['id'])
        tmp = path / ('write_' + secrets.token_hex(12) + '.json')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            durable_flush(f.fileno())
        os.replace(tmp, path / 'draft.json')
        flush_directory(path)
        flush_directory(self.root)

    def _public(self, state: dict[str, Any]) -> dict[str, Any]:
        value = {k: copy.deepcopy(v) for k, v in state.items() if k not in {'bound_spec', 'requests', 'native_session'}}
        ready = bool(state.get('bound_spec') and state.get('proposal') and state['status'] == 'IDLE' and not state.get('mission_id'))
        value['approval_hash'] = digest({'source': state['source'], 'spec': state.get('bound_spec'), 'proposal': state.get('proposal')}) if state.get('proposal') else None
        value['readiness'] = {'ready': ready, 'reason': '工程与验收已就绪，确认后开工。' if ready else ('先在侧栏选择工程并附上固定验收方案；聊天仍可先聊需求。' if not state.get('bound_spec') else '先和 Opus 确认一版完整规划。')}
        value['checks'] = [{'id': key, 'pass_if': check['contract'].get('pass_if'), 'fail_if': check['contract'].get('fail_if')}
                           for key, check in (state.get('bound_spec') or {}).get('checks', {}).items()]
        return redact(value)

    def create(self) -> dict[str, Any]:
        with self.lock:
            if self.closed:
                raise RuntimeError('conversation service is closing')
            ident = 'c_' + secrets.token_hex(16)
            self._path(ident).mkdir(mode=0o700)
            state = {'id': ident, 'title': '新对话', 'status': 'IDLE', 'messages': [], 'source': '', 'spec_path': '',
                     'proposal': None, 'mission_id': None, 'error': None, 'bound_spec': None, 'requests': {},
                     'native_session': None, 'model': {'requested': MODEL, 'actual': None}, 'created_at': now()}
            self._save(state)
            return self._public(state)

    def inventory(self) -> dict[str, Any]:
        with self.lock:
            rows, issues = [], dict(self.issues)
            for path in self.root.glob('c_*'):
                try:
                    state = self._read(path.name)
                    rows.append({key: state.get(key) for key in ('id', 'title', 'status', 'mission_id', 'updated_at')})
                    issues.pop(path.name, None)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    issues[path.name] = {'id': path.name, 'error': error(exc)}
            return {'chats': sorted(rows, key=lambda x: x['updated_at'], reverse=True), 'issues': list(issues.values()), 'auto_start': False}

    def get(self, ident: str) -> dict[str, Any]:
        with self.lock:
            return self._public(self._read(ident))

    @staticmethod
    def _idle(state: dict[str, Any]) -> None:
        if state['status'] in {'RUNNING', 'STARTING', 'UNKNOWN'}:
            raise RuntimeError('request is active or its native outcome needs reconciliation; no automatic resend')
        if state.get('mission_id'):
            raise RuntimeError('conversation is bound to an immutable mission; use mission controls or a new conversation')

    def context(self, ident: str, source: str = '', spec_path: str = '') -> dict[str, Any]:
        if not isinstance(source, str) or not isinstance(spec_path, str):
            raise ValueError('source/spec_path must be text')
        with self.lock:
            if self.closed:
                raise RuntimeError('conversation service is closing')
            state = self._read(ident)
            self._idle(state)
            bound = None
            if spec_path.strip():
                path = Path(spec_path).expanduser().resolve(strict=True)
                if not path.is_file() or path.stat().st_size > 200000:
                    raise ValueError('验收方案应为小于 200 KB 的工程任务 JSON 文件')
                bound = json.loads(path.read_text())
                if source.strip():
                    bound['source'] = source.strip()
                checked = load_lead_spec(bound)
                if any(not x.get('contract', {}).get('fail_if') for x in checked['checks'].values()):
                    raise ValueError('验收方案需要明确通过与失败条件')
                source = checked['source']
                spec_path = str(path)
            if source.strip():
                project = Path(source).expanduser().resolve(strict=True)
                if not project.is_dir() or project.is_relative_to(self.hub.directory) or self.hub.directory.is_relative_to(project):
                    raise ValueError('工程应为现存目录，且与控制目录互相独立')
                source = str(project)
            # A context edit invalidates the old plan and session, rather than
            # showing an old objective as if approved against a new project.
            changed = state['source'] != source or state['spec_path'] != spec_path or state.get('bound_spec') != bound
            state.update(source=source, spec_path=spec_path, bound_spec=bound, error=None, status='IDLE')
            if changed:
                state.update(proposal=None, native_session=None)
                state['messages'].append({'id': secrets.token_hex(8), 'role': 'assistant', 'text': '工程上下文已更新。下一条消息将由 Opus 按新工程重新规划。' + ('固定验收方案已附上，尚未启动执行。' if bound else '你可以先聊需求，再补充验收方案。'), 'created_at': now(), 'kind': 'context'})
            self._save(state)
            return self._public(state)

    def attach_mission(self, ident: str, mission_id: str) -> dict[str, Any]:
        """Reuse the operator's contract, never old results or an active run."""
        from .lead_console import approved_spec
        approved = approved_spec(self.hub.path(mission_id))
        keys = {'schema_version', 'objective', 'source', 'drivers', 'roles', 'checks',
                'required_checks', 'integration_checks', 'parallelism', 'timeout', 'check_timeout',
                'max_turns', 'max_calls', 'max_iterations', 'max_tokens', 'max_cost_usd',
                'max_wall_minutes', 'validation_kind', 'procedure', 'rsi', 'constraints', 'deliverables'}
        raw = {k: v for k, v in approved.items() if k in keys}
        # An initial operator DAG may be reused only with its immutable contracts.
        if approved.get('initial_plan'):
            task_keys = {'id', 'objective', 'depends_on', 'check', 'write_paths', 'acceptance', 'interface', 'repair_of'}
            raw['tasks'] = [{k: v for k, v in task.items() if k in task_keys}
                            for task in approved['initial_plan']['tasks']]
        load_lead_spec(raw)
        with self.lock:
            if self.closed:
                raise RuntimeError('conversation service is closing')
            state = self._read(ident)
            self._idle(state)
            attached = self._path(ident) / ('approved_' + secrets.token_hex(12) + '.json')
            with attached.open('x') as f:
                os.chmod(attached, 0o600)
                json.dump(raw, f, ensure_ascii=False)
            return self.context(ident, raw['source'], str(attached))

    @staticmethod
    def _request_id(value: Any) -> str:
        if not isinstance(value, str) or not _REQUEST.fullmatch(value):
            raise ValueError('request_id must be 8..100 portable characters')
        return value

    def message(self, ident: str, message: str, request_id: str) -> dict[str, Any]:
        request_id = self._request_id(request_id)
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 12000:
            raise ValueError('消息应为 1..12000 个字符')
        with self.lock:
            if self.closed:
                raise RuntimeError('conversation service is closing')
            state = self._read(ident)
            previous = state['requests'].get(request_id)
            fingerprint = hashlib.sha256(message.encode()).hexdigest()
            if previous:
                if previous != {'kind': 'message', 'hash': fingerprint}:
                    raise ValueError('request_id is already bound to another operation')
                return self._public(state)
            self._idle(state)
            if sum(len(x['text'].encode()) for x in state['messages']) + len(message.encode()) > 120000:
                raise ValueError('对话已较长，请新建对话以保留清晰的任务上下文')
            state['requests'][request_id] = {'kind': 'message', 'hash': fingerprint}
            state.update(status='RUNNING', error=None, proposal=None)
            state['messages'].append({'id': request_id, 'role': 'user', 'text': message, 'created_at': now()})
            if len(self._prompt(state).encode()) > 190000:
                raise ValueError('对话上下文接近调用上限，请新建对话并附上精简需求')
            if state['title'] == '新对话':
                state['title'] = message.strip()[:34]
            self._save(state)  # Reservation precedes process dispatch.
            thread = threading.Thread(target=self._reply, args=(ident, request_id), name='opus-chat-' + ident, daemon=False)
            self.threads[ident] = thread
            try:
                thread.start()
            except Exception as exc:
                state.update(status='ERROR', error=error(exc), proposal=None)
                self._save(state)
                raise
            return self._public(state)

    @staticmethod
    def _prompt(state: dict[str, Any]) -> str:
        base = state.get('bound_spec') or {}
        context = {'source': state['source'], 'approved_objective': base.get('objective'),
                   'constraints': base.get('constraints', []), 'deliverables': base.get('deliverables', []),
                   'check_names': list(base.get('checks', {})), 'messages': state['messages']}
        return '''You are the Chinese-speaking Tech Lead in a conversational project interface.
Answer in natural concise Chinese. When returning a proposal, reply should be a brief 150-300 Chinese-character summary rather than repeating the full plan. Put architecture, task details and acceptance in proposal. Use plain text paragraphs, without Markdown emphasis markers. Clarify material unknowns; produce an actionable architecture and acceptance outline when enough is known. You have read-only tools; read the selected source as needed, never modify any file or run commands. No model weights are changed. Do not claim implementation, execution or test success. No mission starts from a chat message. Operator confirms execution separately. Only the attached operator-owned checks can be used for execution; never invent shell commands, executable checks, credentials or fake receipts. If checks are missing explain briefly that a fixed acceptance plan must be attached before execution, while still helping plan the project. Preserve ALL attached constraints/deliverables and objective acceptance requirements. Architecture and task outlines are advisory; core Lead later produces the executable DAG.
Return only strict JSON {"reply":"natural Chinese answer","proposal":null OR {"objective":"self-contained precise execution objective retaining approved requirements and all agreed details","architecture":"module design and interfaces","deliverables":["..."],"constraints":["..."],"tasks":[{"title":"...","acceptance":"...","depends_on":["task title"]}]}}. Do not include tools, commands, checks, roles or budgets in the proposal. Use proposal=null when material unknowns remain.\nContext:\n''' + json.dumps(context, ensure_ascii=False)

    def _reply(self, ident: str, request_id: str) -> None:
        dispatched = False
        receipt = None
        process_started = False
        identity = None
        try:
            with self.lock:
                state = self._read(ident)
                request = Request('chat-' + request_id, self._prompt(state), state['source'] or str(self._path(ident)), MODEL, timeout=600,
                                  max_turns=None, max_output_bytes=8000000, session_id=state.get('native_session'))
            receipt_path = self._path(ident) / ('receipt_' + request_id + '.json')
            events_path = self._path(ident) / ('events_' + request_id + '.jsonl')
            with events_path.open('x') as events:
                os.chmod(events_path, 0o600)
                def emit(kind: str, data: Any) -> None:
                    nonlocal process_started, identity
                    if kind == 'process_started':
                        process_started = True
                    if kind == 'model_identity':
                        identity = copy.deepcopy(data)
                    # Raw native events include internal context; retained locally,
                    # not exposed in chat responses, token-bearing HTTP or logs.
                    events.write(json.dumps(redact({'kind': kind, 'data': data}), ensure_ascii=False) + '\n')
                    events.flush()
                try:
                    dispatched = True
                    receipt = self.driver.run(request, emit).as_dict()
                except Exception as exc:
                    receipt = Receipt('UNKNOWN', error=str(error(exc)), requested_model=MODEL).as_dict()
            with receipt_path.open('x') as f:
                os.chmod(receipt_path, 0o600)
                json.dump(redact(receipt), f, ensure_ascii=False)
                f.flush()
                durable_flush(f.fileno())
            flush_directory(self._path(ident))
            with self.lock:
                state = self._read(ident)
                state['model'] = {'requested': MODEL, 'actual': receipt.get('actual_model')}
                if identity is not None:
                    state['model_identity'] = identity
                if receipt['status'] == 'UNKNOWN' and isinstance(self.driver, ClaudeCodeDriver) and identity is not None and not process_started:
                    state.update(status='ERROR', error={'type': 'NativeLaunchError', 'message': str(redact(receipt.get('error') or '模型进程未启动，请检查本地 CLI 配置。'))[:2000]})
                elif receipt['status'] == 'UNKNOWN':
                    state.update(status='UNKNOWN', error={'type': 'NativeOutcomeUnknown', 'message': str(redact(receipt.get('error') or '请求结果待核对；记录已保留，未重发。'))[:2000]})
                elif receipt['status'] != 'COMPLETED':
                    state.update(status='ERROR', error={'type': 'NativeExecutionError', 'message': str(redact(receipt.get('error') or receipt['status']))[:2000]})
                else:
                    if identity is not None and (identity.get('telemetry') == 'ambiguous' or any(x != MODEL for x in identity.get('reported_models', []))):
                        raise ValueError('native chat execution reports ambiguous or unexpected models')
                    if receipt.get('actual_model') not in {None, MODEL}:
                        raise ValueError('runtime-attested chat model differs from requested Opus')
                    parsed = proposal(strict_json(receipt['output']))
                    state.update(status='IDLE', proposal=parsed.get('proposal'), error=None, native_session=receipt.get('session_id'))
                    state['messages'].append({'id': 'reply-' + request_id, 'role': 'assistant', 'text': parsed['reply'], 'created_at': now(), 'kind': 'opus'})
                self._save(state)
        except Exception as exc:
            with self.lock:
                state = self._read(ident)
                # Transport errors retain UNKNOWN above; deterministic parsing or
                # disk errors remain visible without an automatic repair call.
                uncertain = dispatched and (receipt is None or receipt.get('status') == 'UNKNOWN')
                state.update(status='UNKNOWN' if uncertain else 'ERROR', error=error(exc), proposal=None)
                if receipt is not None:
                    state['model'] = {'requested': MODEL, 'actual': receipt.get('actual_model')}
                if identity is not None:
                    state['model_identity'] = identity
                self._save(state)

    def start(self, ident: str, allow_local_workers: bool, request_id: str, approval_hash: str) -> dict[str, Any]:
        if allow_local_workers is not True:
            raise PermissionError('确认开工需要明确同意本地 Agent 执行')
        request_id = self._request_id(request_id)
        with self.lock:
            if self.closed:
                raise RuntimeError('conversation service is closing')
            state = self._read(ident)
            previous = state['requests'].get(request_id)
            if previous:
                if previous != {'kind': 'start', 'approval_hash': approval_hash}:
                    raise ValueError('request_id already belongs to another operation')
                return self._public(state)
            self._idle(state)
            if not self._public(state)['readiness']['ready']:
                raise ValueError('先附上工程验收方案，并让 Opus 完成一版规划')
            if self.hub.single:
                raise ValueError('现有单任务控制台只管理原任务；新建对话任务请使用 hub')
            if not isinstance(approval_hash, str) or approval_hash != self._public(state)['approval_hash']:
                raise RuntimeError('规划或验收上下文已更新，请查看当前方案并重新确认')
            spec = copy.deepcopy(state['bound_spec'])
            p = state['proposal']
            # Add, never replace, the operator-approved objective/constraints.
            spec['objective'] += '\n\nOperator-confirmed conversation plan:\n' + p['objective'] + '\nArchitecture:\n' + p['architecture'] + '\nTask outline:\n' + json.dumps(p['tasks'], ensure_ascii=False)
            if len(spec['objective']) > 20000:
                raise ValueError('执行目标超过 20000 字符，请缩短方案后重试')
            for key in ('constraints', 'deliverables'):
                spec[key] = list(dict.fromkeys([*spec.get(key, []), *p[key]]))
            spec['source'] = state['source']
            load_lead_spec(spec)  # Revalidate pinned hashes and paths before binding.
            state['requests'][request_id] = {'kind': 'start', 'approval_hash': approval_hash}
            state.update(status='STARTING', error=None)
            self._save(state)
            try:
                created = self.hub.create(spec)
                state['mission_id'] = created['id']
                self._save(state)  # Mapping persists before execution admission.
                self.hub.start(created['id'], allow_local_workers=True)
                state.update(status='IDLE')
                state['messages'].append({'id': 'start-' + request_id, 'role': 'assistant', 'kind': 'control', 'text': '任务已提交给执行控制器。Opus 负责架构、诊断与独立验收，Sol 负责实现。完成状态以测试、审查和集成证据为准。', 'created_at': now()})
            except Exception as exc:
                state.update(status='ERROR', error=error(exc))
                self._save(state)
                raise
            self._save(state)
            return self._public(state)

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            threads = list(self.threads.values())
        for thread in threads:
            thread.join()
        fcntl.flock(self.owner, fcntl.LOCK_UN)
        self.owner.close()
