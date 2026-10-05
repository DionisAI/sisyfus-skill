"""Small controller-owned directory capability, grounded only in user messages.

Prose can suggest a basename inside an explicitly granted HOME parent; it never
supplies a shell command, executable check, execution permission or overwrite.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_PATH = re.compile(r"(?<![A-Za-z0-9:/])(?:\$HOME/|~/|/)[A-Za-z0-9_.\-\u4e00-\u9fff]+(?:/[A-Za-z0-9_.\-\u4e00-\u9fff]+)*")


def paths(text: str, home: Path) -> list[Path]:
    result = []
    for value in _PATH.findall(text):
        value = value.replace('$HOME', str(home), 1) if value.startswith('$HOME') else value
        value = str(home) + value[1:] if value.startswith('~/') else value
        path = Path(value)
        if path not in result:
            result.append(path)
    return result


def directive(message: dict[str, Any]) -> str | None:
    if message.get('role') != 'user':
        return None
    text = message.get('text', '').strip()
    # This deliberately conservative interpreter ignores questions, quoted
    # advice, negations and lengthy pasted material rather than guessing intent.
    if not text or len(text) > 2000 or not re.match(r'^(帮我|请|麻烦|我们|我想|你|在|使用|绑定|设置)', text):
        return None
    if re.search(r'不要|先别|暂不|先不|不需要|解释|介绍|示例|怎么|如何|讨论|能否|能不能|可以.*吗|[“”"\']|```', text):
        return None
    if not re.search(r'目录|文件夹|工程|项目', text):
        return None
    if re.search(r'创建|新建|建立|建一个|建个|建一下', text):
        return 'create'
    if re.search(r'使用已有|使用现有|绑定已有|绑定现有', text):
        return 'bind'
    if re.search(r'填写|设置|设为|绑定', text):
        return 'prepare'
    return None


def directory_request(state: dict[str, Any], home: Path) -> dict[str, Any] | None:
    if state.get('source') or state.get('bound_spec') or state.get('mission_id'):
        return None
    messages = state.get('messages', [])
    users = [m for m in messages if m.get('role') == 'user']
    if not users:
        return None
    latest = users[-1]
    operation = directive(latest)
    if operation is None:
        return None
    explicit = paths(latest['text'], home)
    if any(re.match(r'\s+[A-Za-z0-9_.-]+', latest['text'][match.end():]) for match in _PATH.finditer(latest['text'])):
        return {'status':'NEEDS_CONFIRMATION', 'detail':'目录名称可能含空格；请在聊天里确认完整路径，暂未创建或绑定。'}
    grant = latest
    if not explicit:
        # A follow-up such as "帮我填写工程目录" may use the earlier explicit
        # HOME-create instruction, but never permission from an assistant reply.
        revoked = [i for i,m in enumerate(users) if re.search(r'不要|先别|暂不|先不|不需要',m['text']) and re.search(r'目录|文件夹|工程|项目',m['text'])]
        eligible = users[(revoked[-1] + 1 if revoked else 0):]
        grants = [m for m in eligible if directive(m) == 'create' and re.search(r'\$HOME|~/|主目录|家目录|用户目录', m['text'])]
        if not grants:
            return {'status':'NEEDS_CONFIRMATION', 'detail':'请在聊天里确认目录路径，或明确放在 $HOME 下；无需手动填写设置。'}
        grant = grants[-1]
        grant_paths = paths(grant['text'], home)
        explicit = grant_paths
        operation = 'create'
    if len(explicit) > 1:
        return {'status':'NEEDS_CONFIRMATION', 'detail':'对话中有多个目录路径，请在聊天里确认本次使用哪一个。'}
    if explicit:
        target = explicit[0]
        if operation == 'prepare':
            # "Set project directory to PATH" grants binding if existing,
            # and creation if new; it does not grant overwriting either one.
            operation = 'bind' if target.is_dir() and not target.is_symlink() else 'create'
    else:
        proposal = state.get('proposal') or {}
        hints = paths(str(proposal), home)
        candidates = list(dict.fromkeys(p for p in hints if p.parent == home))
        if hints and (not candidates or len(candidates) != 1):
            return {'status':'NEEDS_CONFIRMATION', 'detail':'方案中的目录路径与已确认范围不一致或有歧义，请在聊天里确认 $HOME 下的项目路径。'}
        target = candidates[0] if candidates else home / ('sisyfus-project-' + state['id'][-8:])
        operation = 'create'
    if not target.is_absolute() or '..' in target.parts or target.name.startswith('.') or target == home:
        return {'status':'NEEDS_CONFIRMATION', 'detail':'请确认一个独立项目目录；不使用根目录、主目录本身或隐藏配置目录。'}
    return {'status':'READY', 'operation':operation, 'path':str(target),
            'instruction_message_id':grant.get('id'), 'trigger_message_id':latest.get('id')}


def open_parent(target: Path, control: Path) -> int:
    if any(p.is_symlink() for p in [target, *target.parents]):
        raise ValueError('目录路径含符号链接；请在聊天里确认实际项目路径。')
    if target == Path('/') or target == control or target.is_relative_to(control) or control.is_relative_to(target):
        raise ValueError('项目目录应与控制目录独立；请确认另一个路径。')
    if not target.parent.is_dir():
        raise ValueError('上级目录尚不存在；请确认现存上级目录下的项目路径。')
    return os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
