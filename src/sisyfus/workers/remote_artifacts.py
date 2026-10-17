"""N3 retained artifact substrate, NOT a remote/native driver or acceptance gate.

Only an explicitly prepared task input tree belongs here: no credentials, other
missions, evaluation material or controller state. Nothing is silently ignored.
The caller pins roots/manifests and enforces NodeClaims identity, epoch, leases
and terminal-receipt eligibility before using this module and again after IO.
Diagnostics/deltas must be recorded by that controller, including on failure.

Snapshot and candidate creation are exclusive. Original inputs, snapshots,
uploads, before copies and failed candidates are retained. The sole removal is
the fixed /usr/bin/trash command on a validated independent candidate file.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Any

from ..autonomy.models import canonical_json
from .node_claims import (MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES,
                          MAX_MANIFEST_BYTES, _directory, _entries,
                          _path, _paths)

MAX_TREE_ENTRIES = 4096
_CLAIM = re.compile(r'claim_[0-9a-f]{32}\Z')


class ArtifactError(ValueError):
    """Explicit retained boundary failure; report contains recordable diagnostics.

Reports contain paths/metadata, never file contents or credentials. This is not
an execution receipt, verifier verdict, retry permission or controller event.
"""

    def __init__(self, report: dict[str, Any]):
        """Expose the complete failure report without fabricating successful IO."""
        self.report = report
        super().__init__('remote artifact boundary: ' + ', '.join(sorted({e['code'] for e in report['errors']})))


def _issue(code: str, path: str = '') -> dict[str, str]:
    """Build content-free relative-path diagnostics for the owning controller."""
    return {'code': code, 'path': path}


def _fail(code: str, path: str = '', report: dict[str, Any] | None = None) -> None:
    """Raise without mutating the caller's report or discarding prior evidence."""
    value = dict(report or {})
    value['errors'] = [*value.get('errors', []), _issue(code, path)]
    value['valid'] = False
    raise ArtifactError(value)


def _root(value: str | Path) -> Path:
    """Accept only controller-provided absolute, non-parent roots; no resolving links."""
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or '\x00' in str(path):
        raise ValueError('root requires an absolute non-parent path')
    return path


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    """Pin inode/type/link count/size/timestamps across bounded regular-file reads."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _subdirectory(root_fd: int, relative: str) -> int:
    """Traverse actual directories relative to a pinned descriptor, never symlinks."""
    fd = os.dup(root_fd)
    try:
        for part in relative.split('/') if relative else []:
            if not part or part in {'.', '..'}:
                raise ValueError('invalid directory component')
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_regular(parent: int, name: str) -> bytes:
    """Read fixed bounded bytes only after lstat and fstat, including race checks.

O_NONBLOCK prevents a substituted FIFO from blocking; type/link checks happen
before any read. Changed bytes/inodes/timestamps produce explicit failure.
"""
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE_BYTES:
        raise ValueError('input requires bounded single-link regular file')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        if _stamp(os.fstat(fd)) != _stamp(before):
            raise ValueError('input changed before read')
        parts, size = [], 0
        while chunk := os.read(fd, 65536):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError('input exceeds file bound')
            parts.append(chunk)
        if size != before.st_size or _stamp(os.fstat(fd)) != _stamp(before):
            raise ValueError('input changed during read')
        return b''.join(parts)
    finally:
        os.close(fd)


def _metadata(path: str, data: bytes) -> dict[str, Any]:
    """Describe validated bytes using the unchanged Node v1 metadata shape."""
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def _payloads(root: Path, entries: list[dict[str, Any]]) -> dict[str, bytes]:
    """Read ALL supplied metadata through one NOFOLLOW root, checking hash and size."""
    result = {}
    fd = _directory(root)
    try:
        for item in entries:
            path = _path(item['path'])
            parts = path.split('/')
            parent = _subdirectory(fd, '/'.join(parts[:-1]))
            try:
                data = _read_regular(parent, parts[-1])
            finally:
                os.close(parent)
            if _metadata(path, data) != item:
                raise ValueError('retained bytes differ from pinned metadata')
            result[path] = data
    finally:
        os.close(fd)
    return result


def _input_manifest(value: Any) -> dict[str, Any]:
    """Validate/detach the exact NodeClaims input shape and combined path collisions."""
    if not isinstance(value, dict) or set(value) != {'files', 'output_paths'}:
        raise ValueError('input requires files and output_paths')
    files = _entries(value['files'])
    outputs = value['output_paths']
    if not isinstance(outputs, list) or len(outputs) > MAX_FILES:
        raise ValueError('output path count exceeds bound')
    outputs = [_path(p) for p in outputs]
    if len(set(outputs)) != len(outputs):
        raise ValueError('duplicate output path')
    _paths([f['path'] for f in files] + outputs)
    result = {'files': files, 'output_paths': sorted(outputs)}
    if len(canonical_json(result).encode('utf-8')) > MAX_MANIFEST_BYTES:
        raise ValueError('input manifest exceeds bound')
    return result


def _file_tree(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Construct the only representable v1 tree: regular files and necessary parents."""
    directories = set()
    for item in files:
        parts = item['path'].split('/')
        directories.update('/'.join(parts[:i]) for i in range(1, len(parts)))
    nodes = [{'path': p, 'kind': 'directory'} for p in directories]
    nodes.extend(dict(f, kind='file') for f in files)
    return {'schema': 1, 'files': sorted(files, key=lambda f: f['path']),
            'tree': sorted(nodes, key=lambda n: n['path']), 'errors': [], 'complete': True}


def full_tree_manifest(root: str | Path) -> dict[str, Any]:
    """Enumerate every actual entry, including hidden/control/link/special paths.

Return {schema:1, files:[Node metadata], tree:[path/kind (+file metadata when
read)], errors:[{code,path}], complete:bool}. Directories are real directories;
symlink/FIFO/device/socket entries are NEVER represented as ordinary files or
read. Unsafe file contents are not read. No mission.files ignore list is used.
128 files/8MB each/32MB total limit hashing; enumeration has a separate fixed
4096-entry bound. Errors retain the observed tree; incomplete enumeration is
explicit, never usable as a complete history or materialization authority.
"""
    report = {'schema': 1, 'files': [], 'tree': [], 'errors': [], 'complete': True}
    try:
        path = _root(root)
        root_fd = _directory(path)
    except (OSError, ValueError, TypeError):
        report['complete'] = False
        report['errors'].append(_issue('root'))
        return report
    count, total, pending = 0, 0, ['']
    aliases = {}
    try:
        while pending:
            relative = pending.pop()
            try:
                fd = _subdirectory(root_fd, relative)
            except (OSError, ValueError):
                report['complete'] = False
                report['errors'].append(_issue('tree_changed', relative))
                continue
            try:
                before = os.fstat(fd)
                names = []
                with os.scandir(fd) as items:
                    for item in items:
                        names.append(item.name)
                        if len(names) + len(report['tree']) > MAX_TREE_ENTRIES:
                            report['complete'] = False
                            report['errors'].append(_issue('tree_limit', relative))
                            break
                for name in sorted(names):
                    if len(report['tree']) >= MAX_TREE_ENTRIES:
                        report['complete'] = False
                        if not any(e['code'] == 'tree_limit' for e in report['errors']):
                            report['errors'].append(_issue('tree_limit', relative))
                        break
                    child = relative + '/' + name if relative else name
                    try:
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    except OSError:
                        report['complete'] = False
                        report['errors'].append(_issue('tree_changed', child))
                        continue
                    kind = ('directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode)
                            else 'symlink' if stat.S_ISLNK(info.st_mode) else 'fifo' if stat.S_ISFIFO(info.st_mode)
                            else 'socket' if stat.S_ISSOCK(info.st_mode) else 'device')
                    node = {'path': child, 'kind': kind}
                    report['tree'].append(node)
                    safe = True
                    try:
                        _path(child)
                    except (ValueError, UnicodeError):
                        safe = False
                        report['errors'].append(_issue('unsafe_path', child))
                    folded = child.casefold()
                    if folded in aliases and aliases[folded] != child:
                        report['errors'].append(_issue('collision', child))
                    aliases[folded] = child
                    if kind == 'directory':
                        # Keep a bounded diagnostic for this actual path, rather than
                        # building unbounded descendant strings outside Node v1 paths.
                        if len(child.encode('utf-8', errors='surrogatepass')) > 1000:
                            report['complete'] = False
                            report['errors'].append(_issue('tree_limit', child))
                        else:
                            pending.append(child)  # Hidden/control directories are still enumerated.
                    elif kind != 'file':
                        report['errors'].append(_issue('symlink' if kind == 'symlink' else 'non_regular', child))
                    else:
                        count += 1
                        total += info.st_size
                        node['size'] = info.st_size
                        readable = safe
                        for invalid, code in ((info.st_nlink != 1, 'hardlink'), (count > MAX_FILES, 'file_count'),
                                              (info.st_size > MAX_FILE_BYTES, 'file_size'), (total > MAX_TOTAL_BYTES, 'total_size')):
                            if invalid:
                                readable = False
                                report['errors'].append(_issue(code, child))
                        if readable:
                            try:
                                data = _read_regular(fd, name)
                                if len(data) != info.st_size or _stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) != _stamp(info):
                                    raise ValueError('tree file changed')
                                metadata = _metadata(child, data)
                                node.update(metadata)
                                report['files'].append(metadata)
                            except (OSError, ValueError):
                                report['errors'].append(_issue('tree_changed', child))
                if _stamp(os.fstat(fd)) != _stamp(before):
                    report['complete'] = False
                    report['errors'].append(_issue('tree_changed', relative))
            except OSError:
                report['complete'] = False
                report['errors'].append(_issue('tree_changed', relative))
            finally:
                os.close(fd)
            if len(report['tree']) >= MAX_TREE_ENTRIES and pending:
                report['complete'] = False
                report['errors'].append(_issue('tree_limit'))
                break
    finally:
        os.close(root_fd)
    report['files'].sort(key=lambda item: item['path'])
    report['tree'].sort(key=lambda item: item['path'])
    return report


def _tree_integrity(value: Any) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Revalidate untrusted whole-tree structure, types, tables, bounds and aliases."""
    errors, nodes = [], {}
    if not isinstance(value, dict) or set(value) != {'schema', 'files', 'tree', 'errors', 'complete'} or value.get('schema') != 1:
        return nodes, [_issue('tree_manifest')]
    if value['complete'] is not True:
        errors.append(_issue('tree_incomplete'))
    if not isinstance(value['errors'], list) or any(not isinstance(e, dict) or set(e) != {'code', 'path'} or
            not isinstance(e['code'], str) or not isinstance(e['path'], str) for e in value['errors']):
        errors.append(_issue('tree_manifest'))
    else:
        errors.extend(dict(e) for e in value['errors'])
    if not isinstance(value['tree'], list) or len(value['tree']) > MAX_TREE_ENTRIES:
        return nodes, errors + [_issue('tree_manifest')]
    files, aliases = [], {}
    for item in value['tree']:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str) or not isinstance(item.get('kind'), str):
            errors.append(_issue('tree_manifest'))
            continue
        path, kind = item['path'], item['kind']
        if path in nodes:
            errors.append(_issue('collision', path))
        nodes[path] = dict(item)
        try:
            _path(path)
        except (ValueError, UnicodeError):
            errors.append(_issue('unsafe_path', path))
        for i in range(1, len(path.split('/')) + 1):
            prefix = '/'.join(path.split('/')[:i])
            folded = prefix.casefold()
            if folded in aliases and aliases[folded] != prefix:
                errors.append(_issue('collision', path))
            aliases[folded] = prefix
        if kind == 'file':
            if set(item) != {'path', 'kind', 'sha256', 'size'}:
                errors.append(_issue('tree_manifest', path))
            else:
                files.append({k: item[k] for k in ('path', 'sha256', 'size')})
        elif kind == 'directory':
            if set(item) != {'path', 'kind'}:
                errors.append(_issue('tree_manifest', path))
        else:
            errors.append(_issue('non_regular', path))
    for path, item in nodes.items():
        parts = path.split('/')
        if any(nodes.get('/'.join(parts[:i]), {}).get('kind') != 'directory' for i in range(1, len(parts))):
            errors.append(_issue('tree_manifest', path))
        if item['kind'] == 'directory' and not any(p.startswith(path + '/') for p in nodes):
            errors.append(_issue('empty_directory', path))
    try:
        validated = _entries(files)
        if _entries(value['files']) != validated:
            errors.append(_issue('tree_files_mismatch'))
    except (ValueError, TypeError, UnicodeError):
        errors.append(_issue('tree_manifest'))
    return nodes, errors


def exact_delta(input_manifest: Any, tree_manifest: Any, uploads: Any, deleted_paths: Any) -> dict[str, Any]:
    """Recompute all file/directory additions, modifications and deletions.

Return sorted added/modified/deleted, added_directories/deleted_directories,
errors and valid. EVERY observed change is checked against fixed output_paths;
changed/new regular files require matching STORED upload metadata. Deletions
must be listed exactly. Unsupported/hidden/control/omitted/colliding trees,
incomplete reads and upload discrepancies are recordable integrity/scope errors.
This pure calculation trusts no patch prose and never writes or accepts a task.
"""
    errors = []
    try:
        manifest = _input_manifest(input_manifest)
    except (ValueError, TypeError, UnicodeError):
        manifest = {'files': [], 'output_paths': []}
        errors.append(_issue('input_manifest'))
    nodes, tree_errors = _tree_integrity(tree_manifest)
    errors.extend(tree_errors)
    before = {item['path']: item for item in manifest['files']}
    outputs = set(manifest['output_paths'])
    non_dirs = {p: item for p, item in nodes.items() if item['kind'] != 'directory'}
    added = sorted(set(non_dirs) - set(before))
    deleted = sorted(set(before) - set(nodes))
    modified = sorted(p for p in set(before) & set(nodes) if nodes[p]['kind'] != 'file' or
                      any(nodes[p].get(k) != before[p][k] for k in ('sha256', 'size')))
    old_dirs = {n['path'] for n in _file_tree(manifest['files'])['tree'] if n['kind'] == 'directory'}
    new_dirs = {p for p, n in nodes.items() if n['kind'] == 'directory'}
    added_dirs, deleted_dirs = sorted(new_dirs - old_dirs), sorted(old_dirs - new_dirs)
    for path in added + modified + deleted:
        if path not in outputs:
            errors.append(_issue('scope', path))
    for path in added_dirs:
        if not any(p.startswith(path + '/') and p in outputs and n['kind'] == 'file' for p, n in nodes.items()):
            errors.append(_issue('scope', path))
    try:
        if not isinstance(deleted_paths, list) or len(deleted_paths) > MAX_FILES:
            raise ValueError('deletion count exceeds bound')
        listed = [_path(p) for p in deleted_paths]
        _paths(listed)
        if len(set(listed)) != len(listed):
            raise ValueError('duplicate deletion')
        if sorted(listed) != deleted:
            errors.append(_issue('deletion_mismatch'))
    except (ValueError, TypeError, UnicodeError):
        errors.append(_issue('deletion_manifest'))
    stored = {}
    try:
        if not isinstance(uploads, list) or any(not isinstance(u, dict) or set(u) != {'path', 'sha256', 'size', 'status'} or
                                               u['status'] != 'STORED' for u in uploads):
            raise ValueError('uploads require exact STORED metadata')
        entries = _entries([{k: u[k] for k in ('path', 'sha256', 'size')} for u in uploads])
        stored = {u['path']: u for u in entries}
    except (ValueError, TypeError, UnicodeError):
        errors.append(_issue('upload_manifest'))
    for path, item in stored.items():
        if path not in outputs:
            errors.append(_issue('scope', path))
        actual = nodes.get(path)
        if not actual or actual['kind'] != 'file':
            errors.append(_issue('unexpected_upload', path))
        elif any(actual.get(k) != item[k] for k in ('sha256', 'size')):
            errors.append(_issue('upload_mismatch', path))
    for path in added + modified:
        if path not in stored:
            errors.append(_issue('missing_upload', path))
    return {'added': added, 'modified': modified, 'deleted': deleted, 'added_directories': added_dirs,
            'deleted_directories': deleted_dirs, 'errors': errors, 'valid': not errors}


def _exclusive_directory(root: Path, *, protected_roots: tuple[Path, ...] = (),
                         report: dict[str, Any] | None = None,
                         parent: _DirectoryPin | None = None) -> int:
    """Create/open one exclusive leaf relative to the checked parent; return its fd.

No missing parent is prepared as a side effect of checking roots. Recheck real
ancestry at the mkdir boundary. Open NOFOLLOW relative to THAT descriptor and
compare lstat/fstat identity before returning ownership of the fd to the caller.
Children borrow their pinned parent, never reopen it for creation by path.
"""
    if parent is not None:
        parent.boundary.check()
        if root.parent != parent.path:
            raise ValueError('child does not belong to pinned parent')
    for protected in protected_roots:
        if _overlap(root, protected):
            _fail('root_overlap', report=report)
    if _root_boundary(root)[2] > 1:
        _fail('missing_parent', report=report)
    parent_fd = parent.fd if parent is not None else _directory(root.parent)
    result = None
    try:
        # This is the descriptor actually used for mkdir, not an alias spelling.
        ancestors = _directory_ancestors(parent_fd)
        for protected in protected_roots:
            protected_id = _root_boundary(protected)[0]
            if protected_id is not None and protected_id in ancestors:
                _fail('root_overlap', report=report)
        os.mkdir(root.name, mode=0o700, dir_fd=parent_fd)
        created = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            if _identity(os.fstat(fd)) != _identity(created) or not stat.S_ISDIR(created.st_mode):
                raise ValueError('created directory changed before open')
            if _directory_ancestors(parent_fd) != ancestors or os.listdir(fd):
                raise ValueError('created directory or parent changed')
            for protected in protected_roots:
                identifier = _root_boundary(protected)[0]
                if identifier is not None and identifier in _directory_ancestors(fd):
                    _fail('root_overlap', report=report)
            os.fsync(parent_fd)
            result = fd
            return fd
        finally:
            if result is None:
                os.close(fd)
    finally:
        if parent is None:
            os.close(parent_fd)


def _identity(info: os.stat_result) -> tuple[int, int]:
    """Physical identity, independent of case/firmlink/path spelling."""
    return info.st_dev, info.st_ino


class _DirectoryPin:
    """One owned directory fd and its recorded namespace, never write authority by path."""

    def __init__(self, fd: int, path: Path, boundary: _IOBoundary, parent: _DirectoryPin | None):
        """Record an already-open exclusive directory; the boundary owns fd closure."""
        self.fd, self.path, self.boundary, self.parent = fd, path, boundary, parent
        self.identifier = _identity(os.fstat(fd))
        self.ancestors = _directory_ancestors(fd)
        self.children: dict[str, _DirectoryPin] = {}
        self.files: dict[str, tuple[int, int]] = {}
        self.retired = False


class _IOBoundary:
    """Keep immutable roots and every created directory pinned through all mutations.

Namespace checks only read paths. Creation, writes and renames always use the
original descriptors. Renamed/unlinked/swapped roots, children or owned files
fail explicitly; unknown existing directories are never adopted or recreated.
The supplied ExitStack closes every descriptor, including interrupted attempts.
"""

    def __init__(self, roots: tuple[Path, ...], stack: ExitStack):
        """Pin protected real identities/ancestors without creating any directory."""
        self.roots, self.stack, self.protected, self.pins = roots, stack, [], []
        for path in roots:
            fd = _directory(path)
            stack.callback(os.close, fd)
            self.protected.append((fd, path, _identity(os.fstat(fd)), _directory_ancestors(fd)))

    def adopt(self, fd: int, path: Path, parent: _DirectoryPin | None = None) -> _DirectoryPin:
        """Own the returned fd immediately, then validate its empty exclusive binding."""
        self.stack.callback(os.close, fd)
        pin = _DirectoryPin(fd, path, self, parent)
        self.pins.append(pin)
        if parent is not None:
            if path.name in parent.children or path.name in parent.files:
                raise ValueError('exclusive child already recorded')
            parent.children[path.name] = pin
        self.check()
        return pin

    def check(self) -> None:
        """Recheck fd identity, live path binding, real ancestry and exact owned names."""
        for fd, path, identifier, ancestors in self.protected:
            self._root_check(fd, path, identifier, ancestors)
        for pin in self.pins:
            if pin.retired:
                continue
            if pin.parent is None:
                self._root_check(pin.fd, pin.path, pin.identifier, pin.ancestors)
            else:
                info = os.stat(pin.path.name, dir_fd=pin.parent.fd, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode) or _identity(info) != pin.identifier:
                    raise ValueError('pinned child binding changed')
                if _identity(os.fstat(pin.fd)) != pin.identifier or _directory_ancestors(pin.fd) != pin.ancestors:
                    raise ValueError('pinned child ancestry changed')
            if set(os.listdir(pin.fd)) != set(pin.children) | set(pin.files):
                raise ValueError('owned directory entries changed')
            for name, identifier in pin.files.items():
                info = os.stat(name, dir_fd=pin.fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _identity(info) != identifier:
                    raise ValueError('owned file identity changed')

    @staticmethod
    def _root_check(fd: int, path: Path, identifier: tuple[int, int], ancestors: set[tuple[int, int]]) -> None:
        """Read-only NOFOLLOW path lookup must still name the pinned actual directory."""
        if _identity(os.fstat(fd)) != identifier or _directory_ancestors(fd) != ancestors:
            raise ValueError('pinned root identity or ancestry changed')
        probe = _directory(path)
        try:
            if _identity(os.fstat(probe)) != identifier:
                raise ValueError('pinned root path changed')
        finally:
            os.close(probe)

    def create(self, parent: _DirectoryPin, name: str) -> _DirectoryPin:
        """Create only one strict relative child below a currently checked pinned fd."""
        _path(name)
        if '/' in name:
            raise ValueError('one child component required')
        path = parent.path / name
        fd = _exclusive_directory(path, protected_roots=self.roots, parent=parent)
        return self.adopt(fd, path, parent)

    def parent(self, pin: _DirectoryPin, relative: str, *, create: bool = False) -> tuple[_DirectoryPin, str]:
        """Traverse recorded child descriptors; exclusively create only below them."""
        _path(relative)
        for part in relative.split('/')[:-1]:
            self.check()
            child = pin.children.get(part)
            if child is None:
                if not create:
                    raise ValueError('unrecorded directory')
                child = self.create(pin, part)
            pin = child
        self.check()
        return pin, relative.split('/')[-1]


def _write_file(root: Path, path: str, data: bytes, *, pinned: _DirectoryPin, replace: bool = False) -> None:
    """Write verified bytes through owned pinned fds; path is a diagnostic only.

Parents are exclusive children of the pinned root, never an absolute create=True
lookup. Replacement requires the SAME recorded single-link candidate inode.
Check namespace/ancestry before each mutation, including after opening the file.
No incomplete file is removed on error; file and parent durability are explicit.
"""
    if root != pinned.path:
        raise ValueError('write path differs from pinned root')
    boundary = pinned.boundary
    parent, name = boundary.parent(pinned, path, create=True)
    flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if replace:
        if name not in parent.files:
            raise ValueError('replacement is not an owned file')
    else:
        flags |= os.O_CREAT | os.O_EXCL
    boundary.check()
    fd = os.open(name, flags, 0o600, dir_fd=parent.fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('candidate requires single-link regular file')
        if replace and _identity(info) != parent.files[name]:
            raise ValueError('candidate file changed before replacement')
        parent.files[name] = _identity(info)
        boundary.check()
        if replace:
            os.ftruncate(fd, 0)
        offset = 0
        while offset < len(data):
            boundary.check()
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError('artifact write made no progress')
            offset += written
        boundary.check()
        os.fsync(fd)
        os.fsync(parent.fd)
    finally:
        os.close(fd)


def _directory_ancestors(directory: int) -> set[tuple[int, int]]:
    """Walk a pinned directory's REAL ancestors to / using NOFOLLOW descriptors.

dev/inode identity includes the directory itself. Never infer ancestry from
path spelling, case folding or resolve(); firmlink aliases need real '..'.
Stat/open disagreement, cycles or an excessive chain fail before mutation.
"""
    fd = os.dup(directory)
    ancestors = set()
    try:
        for _ in range(MAX_TREE_ENTRIES):
            info = os.fstat(fd)
            current = (info.st_dev, info.st_ino)
            if current in ancestors:
                raise ValueError('directory ancestry cycle')
            ancestors.add(current)
            parent = os.stat('..', dir_fd=fd, follow_symlinks=False)
            parent_id = (parent.st_dev, parent.st_ino)
            if not stat.S_ISDIR(parent.st_mode):
                raise ValueError('directory ancestry is not a directory')
            if parent_id == current:
                return ancestors
            nxt = os.open('..', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            actual = os.fstat(nxt)
            if (actual.st_dev, actual.st_ino) != parent_id:
                os.close(nxt)
                raise ValueError('directory ancestry changed')
            os.close(fd)
            fd = nxt
        raise ValueError('directory ancestry exceeds bound')
    finally:
        os.close(fd)


def _root_boundary(root: Path) -> tuple[tuple[int, int] | None, set[tuple[int, int]], int]:
    """Inspect a root or its nearest EXISTING parent without creating anything.

Only ENOENT permits probing a shorter path; symlinks/non-directories/permission
errors propagate. Path.parent locates a probe, never determines identity or
ancestry. Return (existing root identity or None, actual ancestor ids, number
of missing trailing components). More than one missing component needs explicit
controller parent preparation, outside this module's exclusive-leaf capability.
"""
    probe, missing = root, 0
    while True:
        try:
            fd = _directory(probe)
            break
        except FileNotFoundError:
            if probe.parent == probe:
                raise
            probe = probe.parent
            missing += 1
    try:
        info = os.fstat(fd)
        identifier = (info.st_dev, info.st_ino) if missing == 0 else None
        return identifier, _directory_ancestors(fd), missing
    finally:
        os.close(fd)


def _overlap(first: Path, second: Path) -> bool:
    """Reject physical equality and either nesting direction, including new roots.

For a missing destination, its nearest existing directory's real ancestry is
checked. A shared ancestor alone is not overlap between disjoint siblings.
"""
    first_id, first_ancestors, _ = _root_boundary(first)
    second_id, second_ancestors, _ = _root_boundary(second)
    return ((first_id is not None and first_id in second_ancestors) or
            (second_id is not None and second_id in first_ancestors))


def create_input_snapshot(source: str | Path, snapshot: str | Path, output_paths: list[str]) -> dict[str, Any]:
    """Freeze all approved regular-file bytes into one exclusive persistent snapshot.

Return the exact NodeClaims {files, output_paths} manifest; the caller persists
its hash/ownership before publishing an offer. Source must be a prepared task
tree, not a whole repository with ignored control/credential/evaluation files.
Reject unsafe/special/hidden/control/colliding/empty-directory/oversized input,
missing source, physically overlapping roots and changed input. Only one leaf
under an existing parent is created; missing parent chains fail explicitly and
are never prepared while checking. Keep the new leaf descriptor pinned through
all writes; broken root/parent bindings fail without rebuilding them. Sync bytes and verify
both trees after copying. Errors retain original material and any created partial
snapshot, with explicit ArtifactError.report; no ignored paths or fake success.
"""
    try:
        source_root, snapshot_root = _root(source), _root(snapshot)
        if _overlap(source_root, snapshot_root):
            _fail('root_overlap')
        before = full_tree_manifest(source_root)
        _, errors = _tree_integrity(before)
        if errors:
            raise ArtifactError(dict(before, errors=errors))
        try:
            manifest = _input_manifest({'files': before['files'], 'output_paths': output_paths})
        except (ValueError, TypeError, UnicodeError):
            _fail('input_manifest')
        try:
            data = _payloads(source_root, manifest['files'])
        except (OSError, ValueError):
            _fail('input_changed')
        if full_tree_manifest(source_root) != before:
            _fail('input_changed')
        with ExitStack() as stack:
            boundary = _IOBoundary((source_root,), stack)
            fd = _exclusive_directory(snapshot_root, protected_roots=(source_root,))
            pinned = boundary.adopt(fd, snapshot_root)
            for item in manifest['files']:
                _write_file(snapshot_root, item['path'], data[item['path']], pinned=pinned)
            boundary.check()
            if full_tree_manifest(snapshot_root) != before:
                _fail('snapshot_mismatch')
            if full_tree_manifest(source_root) != before:
                _fail('input_changed')
            boundary.check()
            return manifest
    except ArtifactError:
        raise
    except (OSError, ValueError, TypeError):
        _fail('io_error')


def _trash_failure_location(report: dict[str, Any], parent: _DirectoryPin | None,
                            stage: _DirectoryPin | None, name: str,
                            item: dict[str, Any] | None, identifier: tuple[int, int] | None,
                            moved: bool, attempted: bool, failure_type: str) -> dict[str, Any]:
    """Observe owned copies via pinned NOFOLLOW fds; never invent a recovery path.

Advertise a location only after its live root binding, original object identity
and bytes (or owned empty directory) are verified. Inspection races/errors are
diagnostics, not replacements for the original failure. Absence after a Trash
attempt says nothing about its destination. No recovery moves occur here.
    """
    evidence = dict(report)
    observed = {'moved': moved, 'trash_attempted': attempted, 'failure_type': failure_type}
    for label, pin in (('staging', stage), ('candidate', parent)):
        if pin is None:
            observed[label] = 'NOT_INSPECTED'
            continue
        try:
            _IOBoundary._root_check(pin.fd, pin.path, pin.identifier, pin.ancestors)
            try:
                info = os.stat(name, dir_fd=pin.fd, follow_symlinks=False)
            except FileNotFoundError:
                _IOBoundary._root_check(pin.fd, pin.path, pin.identifier, pin.ancestors)
                observed[label] = 'ABSENT'
                continue
            verified = _identity(info) == identifier
            if item is not None:
                verified = (verified and stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                            _metadata(item['path'], _read_regular(pin.fd, name)) == item)
            elif verified and stat.S_ISDIR(info.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=pin.fd)
                try:
                    verified = _identity(os.fstat(fd)) == identifier and not os.listdir(fd)
                finally:
                    os.close(fd)
            else:
                verified = False
            _IOBoundary._root_check(pin.fd, pin.path, pin.identifier, pin.ancestors)
            verified = verified and _stamp(os.stat(name, dir_fd=pin.fd, follow_symlinks=False)) == _stamp(info)
            observed[label] = 'PRESENT' if verified else 'UNVERIFIED'
            if verified:
                evidence['retained_' + label] = {'root': str(pin.path), 'object': str(pin.path / name)}
        except Exception as exc:
            observed[label] = 'UNKNOWN'
            observed[label + '_inspection_error'] = type(exc).__name__
    evidence['failure_location'] = observed
    if attempted:
        evidence['trash_outcome'] = 'UNKNOWN'
    return evidence


def _stage_trash(pinned: _DirectoryPin, path: str, envelope: _DirectoryPin,
                 report: dict[str, Any], item: dict[str, Any] | None = None) -> None:
    """Move a verified owned copy to a private exclusive staging fd, then Trash it.

Both file and empty-directory moves use src_dir_fd/dst_dir_fd, never a candidate
absolute path. Each new 0700 staging directory contains exactly one flat object,
with no pre-existing destination; a collision fails before rename. Check its
identity/binding/ancestry before Trash and after; any failure retains staging,
before and originals. The sole final removal is /usr/bin/trash <absolute-object>.
    """
    boundary = pinned.boundary
    stage = parent = None
    name, identifier = path.split('/')[-1], None
    moved = attempted = False
    try:
        parent, name = boundary.parent(pinned, path)
        if item is not None:
            if name not in parent.files or _metadata(path, _read_regular(parent.fd, name)) != item:
                raise ValueError('deletion copy differs from fixed input')
            identifier = parent.files[name]
            child = None
        else:
            child = parent.children.get(name)
            if child is None or os.listdir(child.fd):
                raise ValueError('deletion directory is not owned and empty')
            identifier = child.identifier
        stage = boundary.create(envelope, 'trash-' + secrets.token_hex(16))
        try:
            os.stat(name, dir_fd=stage.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass  # Fresh exclusive staging has no destination to overwrite.
        else:
            raise ValueError('staging destination exists')
        boundary.check()
        os.rename(name, name, src_dir_fd=parent.fd, dst_dir_fd=stage.fd)
        moved = True
        if child is None:
            stage.files[name] = parent.files.pop(name)
            if _metadata(path, _read_regular(stage.fd, name)) != item:
                raise ValueError('staged bytes changed')
        else:
            parent.children.pop(name)
            stage.children[name] = child
            child.parent, child.path = stage, stage.path / name
            child.ancestors = _directory_ancestors(child.fd)
        os.fsync(parent.fd)
        os.fsync(stage.fd)
        boundary.check()
        attempted = True
        subprocess.run(['/usr/bin/trash', str(stage.path / name)], check=True, capture_output=True, text=True)
        try:
            os.stat(name, dir_fd=stage.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass  # The verified copy remains recoverable in Trash and before.
        else:
            evidence = _trash_failure_location(report, parent, stage, name, item, identifier,
                                               moved, attempted, 'TrashObjectRemains')
            _fail('trash_failed', path, evidence)
        if child is None:
            stage.files.pop(name)
        else:
            stage.children.pop(name)
            child.retired = True
        os.fsync(stage.fd)
        boundary.check()
    except ArtifactError:
        raise
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        evidence = _trash_failure_location(report, parent, stage, name, item, identifier,
                                           moved, attempted, type(exc).__name__)
        _fail('trash_failed', path, evidence)


def _trash_candidate(root: Path, item: dict[str, Any], report: dict[str, Any], *,
                     pinned: _DirectoryPin, envelope: _DirectoryPin) -> None:
    """Stage/Trash only an owned pinned candidate file, never its absolute lookup."""
    if root != pinned.path:
        raise ValueError('deletion path differs from pinned candidate')
    _stage_trash(pinned, item['path'], envelope, report, item)


def materialize_candidate(snapshot: str | Path, input_manifest: Any, tree_manifest: Any,
                          uploads: Any, deleted_paths: Any, *, artifact_root: str | Path,
                          claim_id: str, candidate_root: str | Path) -> dict[str, Any]:
    """Validate ALL inputs/tree/uploads before creating an independent candidate.

The upload root is ONLY artifact_root/claim_<32 lowercase hex>; upload metadata
cannot supply absolute source paths or another claim. NodeClaims owns namespace
identity, pinned root/hash, lease and receipt currency; these checks are required
by the caller before and after IO. This module does not confer that authority.

Check real root/ancestor identity (including claim root) before mutation. New
envelopes require an existing disjoint parent, not implicit parent preparation.
Recheck retained snapshot and every STORED byte (NOFOLLOW/hash/size), recompute
exact delta/scope/deletions, then create candidate_root exclusively with fixed
before/ and candidate/ subtrees. Pin all created directories until IO completes;
broken/replaced bindings never recreate parents or redirect writes. Only verified
bytes are written. Rename deletion copies through pinned fds into exclusive private
staging siblings before recoverable Trash; retain failed staging and original data.
Reverify resulting full trees. Return {candidate,before,delta}; failure raises
ArtifactError with recordable diagnostics and retains all partial candidates.
Neither this return nor a native receipt is verifier PASS/integration evidence.
"""
    delta = exact_delta(input_manifest, tree_manifest, uploads, deleted_paths)
    if not delta['valid']:
        raise ArtifactError(delta)
    try:
        if not isinstance(claim_id, str) or not _CLAIM.fullmatch(claim_id):
            _fail('namespace', report=delta)
        input_root, artifacts, envelope = _root(snapshot), _root(artifact_root), _root(candidate_root)
        claim_root = artifacts / claim_id
        protected = (input_root, artifacts, claim_root)
        if (_overlap(input_root, artifacts) or _overlap(input_root, claim_root) or
                any(_overlap(envelope, root) for root in protected)):
            _fail('root_overlap', report=delta)
        manifest = _input_manifest(input_manifest)
        expected_before = _file_tree(manifest['files'])
        if full_tree_manifest(input_root) != expected_before:
            _fail('snapshot_mismatch', report=delta)
        try:
            inputs = _payloads(input_root, manifest['files'])
        except (OSError, ValueError):
            _fail('snapshot_mismatch', report=delta)
        entries = _entries([{k: u[k] for k in ('path', 'sha256', 'size')} for u in uploads])
        try:
            fd = _directory(claim_root)  # Validate namespace even if no uploads exist.
            os.close(fd)
            data = _payloads(claim_root, entries)
        except (OSError, ValueError):
            _fail('upload_bytes', report=delta)
        if full_tree_manifest(input_root) != expected_before:
            _fail('snapshot_mismatch', report=delta)
        if delta['deleted']:
            try:
                info = os.stat('/usr/bin/trash', follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or not os.access('/usr/bin/trash', os.X_OK):
                    _fail('trash_unavailable', report=delta)
            except OSError:
                _fail('trash_unavailable', report=delta)
        with ExitStack() as stack:
            boundary = _IOBoundary(protected, stack)
            try:
                fd = _exclusive_directory(envelope, protected_roots=protected, report=delta)
            except FileExistsError:
                _fail('candidate_exists', report=delta)
            envelope_pin = boundary.adopt(fd, envelope)
            before_pin, candidate_pin = boundary.create(envelope_pin, 'before'), boundary.create(envelope_pin, 'candidate')
            before, candidate = before_pin.path, candidate_pin.path
            for item in manifest['files']:
                _write_file(before, item['path'], inputs[item['path']], pinned=before_pin)
            for item in manifest['files']:
                _write_file(candidate, item['path'], inputs[item['path']], pinned=candidate_pin)
            for path in delta['deleted']:
                _trash_candidate(candidate, next(i for i in manifest['files'] if i['path'] == path), delta,
                                 pinned=candidate_pin, envelope=envelope_pin)
            for path in delta['added'] + delta['modified']:
                _write_file(candidate, path, data[path], replace=path in inputs, pinned=candidate_pin)
            for path in sorted(delta['deleted_directories'], key=lambda p: (-p.count('/'), p)):
                _stage_trash(candidate_pin, path, envelope_pin, delta)
            boundary.check()
            expected_after = _file_tree(_entries(tree_manifest['files']))
            if full_tree_manifest(candidate) != expected_after or full_tree_manifest(before) != expected_before:
                _fail('materialized_mismatch', report=delta)
            if full_tree_manifest(input_root) != expected_before:
                _fail('snapshot_mismatch', report=delta)
            if _payloads(claim_root, entries) != data:
                _fail('upload_bytes', report=delta)
            boundary.check()
            return {'candidate': str(candidate), 'before': str(before), 'delta': delta}
    except ArtifactError:
        raise
    except subprocess.CalledProcessError:
        _fail('trash_failed', report=delta)
    except (OSError, ValueError, TypeError):
        _fail('io_error', report=delta)
