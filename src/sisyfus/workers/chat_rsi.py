"""Explicit chat directives configure RSI; models never select evaluation truth.

Preparation inspects only the public catalog manifest. It does not read case
specs, source or holdout content, consume holdout, reserve native calls or create
missions. The controller's existing paired runner owns those later boundaries.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from .lead_trials import _json
from .protocol import redact

CAPS = ('max_calls', 'max_iterations', 'max_tokens', 'max_cost_usd', 'max_wall_minutes')
_COMMAND = re.compile(
    r'^(?:请|帮我|请帮我)?\s*(?:(?:为|给|在)(?:这个工程|这项任务|本工程|这个项目)(?:上|中)?\s*)?(?:先\s*)?'
    r'(?:(开启|打开|启用|启动|运行|配置|关闭|禁用|停用)\s*RSI\b|'
    r'RSI\s*(开启|启用|关闭|禁用|停用|只评估|仅评估)|使用(?:已有)?\s*RSI\s*评估集)', re.I)
_PATH = re.compile(r'`([^`]+)`|"([^"]+)"|\u201c([^\u201d]+)\u201d|(/[^\s`"\u201c\u201d，。；;<>]+)')


def instruction(message: str, pending: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Recognize a small imperative language, never quoted/advisory model prose."""
    text = message.strip()
    match = _COMMAND.match(text)
    followup = bool(pending and pending.get('status') in {'NEEDS_INPUT', 'ERROR'} and
                    pending.get('configuration', {}).get('enabled', True) and
                    (re.match(r'^(?:RSI\s*)?(?:评估集(?:目录)?|评估目录)', text, re.I) or
                     not pending.get('configuration', {}).get('evaluation_root') and _PATH.fullmatch(text)))
    if (not match and not followup) or re.search(r'[?？]|(?:吗|么)[。！!]?$', text):
        return None
    if match and re.match(r'^(?:的|后|前|时|会|意味着)', text[match.end():].lstrip()):
        return None
    verb = (match.group(1) or match.group(2) or '启用') if match else '启用'
    enabled = verb not in {'关闭', '禁用', '停用'}
    auto = None
    if re.search(r'只评估|仅评估|(?:不|禁止|不要|先别)自动(?:晋升|采用)|手动晋升', text):
        auto = False
    elif re.search(r'自动(?:晋升|采用)', text):
        auto = True
    # Only the explicitly named evaluation catalog supplies a path. Project
    # paths, assistant suggestions and unrelated earlier messages are ignored.
    label = re.search(r'评估集(?:目录)?|评估目录|(?<![/\w])catalog\b', text, re.I)
    roots = [] if label is None and not followup else [next(x for x in item if x) for item in _PATH.findall(text[label.end():] if label else text)]
    return {'enabled': enabled, 'auto_promote': auto,
            'evaluation_root': roots[0] if len(roots) == 1 else None,
            'issue': '评估集路径有歧义，请只指定一个绝对目录。' if len(roots) > 1 else None}


def planning_text(message: str) -> str:
    """Keep the user's other goals while withholding controller catalog paths."""
    return _PATH.sub(lambda match: '[控制器持有的评估集路径]' if next(x for x in match.groups() if x).startswith(('/', '~')) else match.group(0), message)


def _catalog(root: str, hub: Path, source: str) -> tuple[Path, dict[str, Any]]:
    path = Path(root).expanduser()
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('评估集需为绝对路径且路径中无符号链接。')
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError('评估集目录不存在。')
    for other in (hub.resolve(), Path(source).resolve() if source else None):
        if other is not None and (path.is_relative_to(other) or other.is_relative_to(path)):
            raise ValueError('评估集须与工程和控制目录互相独立。')
    raw, manifest_hash = _json(path / 'manifest.json')
    if not isinstance(raw, dict) or set(raw) - {'schema', 'search', 'holdout'}:
        raise ValueError('评估集 manifest 字段应为 schema、search、holdout。')
    ids, counts = set(), {}
    for split in ('search', 'holdout'):
        entries = raw.get(split)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise ValueError(split + ' 需包含 1..64 个独立固定案例。')
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {'id', 'spec', 'source_missions', 'source_mission_ids', 'source_family_hashes'}:
                raise ValueError('评估案例字段有误。')
            ident = entry.get('id')
            if not isinstance(ident, str) or not 1 <= len(ident) <= 200 or ident in ids:
                raise ValueError('评估案例编号须非空且互不重复。')
            if not isinstance(entry.get('spec'), str) or not entry['spec'].strip():
                raise ValueError('聊天准备需使用 spec 文件路径引用，不内嵌案例内容；完整案例留给配对评估器读取。')
            ids.add(ident)
        counts[split + '_cases'] = len(entries)
    return path, {**counts, 'manifest_hash': manifest_hash,
                  'scope': 'manifest_only; case content and holdout not inspected'}


def validate(config: dict[str, Any], base: dict[str, Any], hub: Path, source: str) -> dict[str, Any] | None:
    """Revalidate at Start before any mission/native reservation."""
    if not config.get('enabled', True):
        return None
    caps = [name for name in CAPS if base.get(name) is not None]
    if caps:
        raise ValueError('RSI 子试验需总预算 Unlimited；当前保留的有限预算：' + '、'.join(caps) + '。请审阅新的预算合同后再绑定，不自动放宽限制。')
    root = config.get('evaluation_root')
    if not isinstance(root, str) or not root:
        raise ValueError('请在聊天里指定固定评估集的绝对目录，例如：开启 RSI，评估集目录为 `/绝对路径/catalog`。')
    _, catalog = _catalog(root, hub, source)
    expected = config.get('evaluation_manifest_hash')
    if expected and expected != catalog['manifest_hash']:
        raise ValueError('评估集 manifest 已变化，请在聊天里重新指定评估集并审阅新方案。')
    return catalog


def prepare(action: dict[str, Any], base: dict[str, Any], hub: Path, source: str) -> dict[str, Any]:
    config = copy.deepcopy(base.get('rsi') or {'enabled': True, 'auto_promote': True})
    config['enabled'] = action['enabled']
    if action['auto_promote'] is not None:
        config['auto_promote'] = action['auto_promote']
    if action['evaluation_root']:
        config['evaluation_root'] = action['evaluation_root']
        config.pop('evaluation_manifest_hash', None)
    record = {'status': 'NEEDS_INPUT', 'configuration': config, 'catalog': None}
    if not config['enabled']:
        config = {'enabled': False, 'auto_promote': False}
        return {**record, 'status': 'CONFIGURED', 'configuration': config,
                'detail': 'RSI 已关闭。工程编排与固定验收保持原合同；尚未派发任务。'}
    if action['issue']:
        return {**record, 'detail': action['issue']}
    caps = [name for name in CAPS if base.get(name) is not None]
    if not config.get('evaluation_root') or caps:
        try:
            validate(config, base, hub, source)
        except ValueError as exc:
            return {**record, 'detail': str(exc)}
    try:
        path, catalog = _catalog(config['evaluation_root'], hub, source)
        config.update(evaluation_root=str(path), evaluation_manifest_hash=catalog['manifest_hash'])
    except (OSError, ValueError, TypeError) as exc:
        return {**record, 'status': 'ERROR', 'detail': '评估集准备出现问题（' + type(exc).__name__ + '），请核对目录与 manifest；具体诊断已保留。',
                'error': {'type': type(exc).__name__, 'message': str(redact(str(exc)))[:2000]}}
    return {**record, 'status': 'CONFIGURED', 'configuration': config, 'catalog': catalog,
            'detail': 'RSI 已配置：search %s 例，holdout %s 例；%s。仅核对目录清单，未读取 holdout 内容，未派发任务。开工后由控制器执行 baseline/candidate 对照与独立 holdout 验收。' % (
                catalog['search_cases'], catalog['holdout_cases'], '通过全部门槛后自动晋升' if config.get('auto_promote', True) else '只评估，不自动晋升')}
