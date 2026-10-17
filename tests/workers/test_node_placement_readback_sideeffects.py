"""Frozen v2 side-effect races while production readback source is on HOLD.

Real renamed originals, empty replacement directory and foreign DELETE-journal
DB. Observe file creation/header mutation even when GET rejects. Live committed
WAL frames and copied real WAL/shm images cover the auxiliary-file boundary too.
Strict tree equality is a candidate zero-filesystem-effect check, not approval
of a new WAL permission contract. Primitive checks are not a production repair.
No original-store hook is replaced. All displaced files, full tree/header
snapshots and observed DB/WAL/shm bytes are retained outside the observed tree.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from sisyfus.workers import lead_console as console
from test_node_operator_http import call
from test_node_placement_readback_race import env, offline_guard, read_guard


def full_tree(root):
    """No follow, no atime comparison, no SQLite open; inspect every entry."""
    result = {}

    def visit(path):
        info = path.lstat()
        key = path.relative_to(root).as_posix()
        value = {'dev': info.st_dev, 'ino': info.st_ino, 'mode': info.st_mode,
                 'nlink': info.st_nlink, 'mtime_ns': info.st_mtime_ns,
                 'ctime_ns': info.st_ctime_ns}
        if stat.S_ISREG(info.st_mode):
            data = path.read_bytes()
            value.update(kind='file', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            if path.name.endswith(('sqlite3', 'sqlite3-wal', 'sqlite3-shm')):
                value['header_hex'] = data[:128].hex()
                if path.name.endswith('sqlite3'):
                    value['header_versions'] = list(data[18:20])
        elif stat.S_ISDIR(info.st_mode):
            value['kind'] = 'directory'
        elif stat.S_ISLNK(info.st_mode):
            value.update(kind='symlink', target=str(path.readlink()))
        else:
            value['kind'] = 'other'
        result[key] = value
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()):
                visit(child)

    visit(root)
    return result


class Evidence:
    def __init__(self, root, directory):
        self.root, self.directory, self.count = root, directory, 0

    def capture(self, label):
        tree = full_tree(self.root)
        packet = self.directory / f'{self.count:03d}'
        self.count += 1
        packet.mkdir()
        with (packet / 'tree.json').open('x') as stream:
            json.dump({'label': label, 'root': str(self.root), 'tree': tree}, stream, sort_keys=True)
        for relative, item in tree.items():
            if 'header_hex' in item:
                # Retain full observed bytes, not just a hash or post-close view.
                with (packet / (hashlib.sha256(relative.encode()).hexdigest() + '.bin')).open('xb') as stream:
                    stream.write((self.root / relative).read_bytes())
        return tree


@pytest.fixture
def side(env, tmp_path_factory):
    folder = env.root / 'foreign-rollback'
    folder.mkdir()
    database = folder / 'autonomy.sqlite3'
    db = sqlite3.connect(database)
    try:
        db.executescript('\n'.join(env.before_b))
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    finally:
        db.close()
    before = database.read_bytes()
    assert before[18:20] == b'\x01\x01'
    assert not Path(str(database) + '-wal').exists()
    assert not Path(str(database) + '-shm').exists()
    (env.root / 'foreign-rollback.before.bin').open('xb').write(before)
    evidence = Evidence(env.root, tmp_path_factory.mktemp('physical-readback-evidence'))
    print('FULL_TREE_HEADER_EVIDENCE', evidence.directory)
    evidence.capture('fixture_ready')
    return SimpleNamespace(env=env, database=database, before=before, evidence=evidence)


def physical(database):
    result = {}
    for suffix in ('', '-wal', '-shm'):
        path = Path(str(database) + suffix)
        data = path.read_bytes() if path.is_file() else None
        result[suffix or 'db'] = {
            'exists': path.exists(), 'bytes': len(data) if data is not None else None,
            'sha256': hashlib.sha256(data).hexdigest() if data is not None else None,
            'header_versions': list(data[18:20]) if data is not None and len(data) >= 20 else None}
    return result


def real_swap(side, kind):
    env = side.env
    target = env.a.store.path
    state = {'done': False, 'retained': None, 'at_swap': None, 'tree_at_swap': None}

    def swap():
        assert not state['done']
        side.evidence.capture('before_' + kind + '_replacement')
        state['done'] = True
        if kind == 'empty_directory':
            retained = env.root / 'retained-original-control'
            env.a.directory.rename(retained)
            env.a.directory.mkdir()
            state['retained'] = retained / 'autonomy.sqlite3'
        else:
            retained = env.root / 'retained-original.sqlite3'
            target.rename(retained)
            state['retained'] = retained
            for suffix in ('-wal', '-shm'):
                original_auxiliary = Path(str(target) + suffix)
                if original_auxiliary.exists():
                    original_auxiliary.rename(Path(str(retained) + suffix))
            if kind == 'foreign_rollback':
                side.database.rename(target)
        state['at_swap'] = physical(target)
        state['tree_at_swap'] = side.evidence.capture('after_' + kind + '_replacement_before_open')
    return swap, state


def assert_no_side_effect(side, kind, state, observations):
    target = side.env.a.store.path
    assert state['done'], 'pre-open real swap was not reached'
    assert state['retained'].is_file(), 'original database was not retained'
    after = physical(target)
    tree_after = side.evidence.capture('after_read_or_rejected_get')
    print(json.dumps({'kind': kind, 'at_swap': state['at_swap'],
                      'observed': observations, 'after': after}, sort_keys=True))
    if kind in ('missing_database', 'empty_directory'):
        assert not any(value['exists'] for value in after.values()), 'GET created a new database/sidecar'
        assert not any(value['exists'] for _, view in observations for value in view.values()), \
            'GET transiently created a database/sidecar before rejecting the request'
    else:
        assert target.read_bytes() == side.before, 'GET mutated a foreign rollback database header/bytes'
        assert after['db']['header_versions'] == [1, 1]
        assert not after['-wal']['exists'] and not after['-shm']['exists']
        assert all(view['db']['sha256'] == hashlib.sha256(side.before).hexdigest()
                   and not view['-wal']['exists'] and not view['-shm']['exists']
                   for _, view in observations), 'GET changed foreign DB/sidecars before its fence'
    assert tree_after == state['tree_at_swap'], 'read changed the retained fixture tree'


@pytest.mark.parametrize('mode', ['warm', 'cold'])
@pytest.mark.parametrize('kind', ['missing_database', 'empty_directory', 'foreign_rollback'])
def test_get_preopen_race_has_no_database_or_header_write_authority(side, monkeypatch, mode, kind):
    env = side.env
    hub = env.h if mode == 'warm' else console.MissionHub(env.h.directory)
    target = env.a.store.path
    raw_connect = sqlite3.connect
    swap, state = real_swap(side, kind)
    opens, observations = [], []

    def observe(label):
        observations.append((label, physical(target)))
        side.evidence.capture('readback_open_' + label)

    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            try:
                return super().execute(sql, parameters)
            finally:
                if self.index == 2:
                    observe(sql)

        def close(self):
            if self.index == 2:
                observe('before_close')
            return super().close()

    def connect(path, *args, **kwargs):
        text = str(path)
        if text != str(target) and not text.startswith(target.as_uri() + '?'):
            return raw_connect(path, *args, **kwargs)
        opens.append(text)
        index = len(opens)
        if index == 2:
            swap()  # After the caller's last identity check, before actual open.
        assert 'factory' not in kwargs
        try:
            db = raw_connect(path, *args, factory=Connection, **kwargs)
        except Exception:
            if index == 2:
                observe('open_error')
            raise
        db.index = index
        if index == 2:
            observe('after_open')
        return db

    with monkeypatch.context() as guard:
        read_guard(hub, guard)
        guard.setattr(console.sqlite3, 'connect', connect)
        side.evidence.capture('before_get')
        code, value = call(hub, '/api/missions/' + env.ident + '/placements')
    assert len(opens) == 2
    assert_no_side_effect(side, kind, state, observations)
    assert code == 403 and value['error']['type'] == 'PermissionError'
    assert 'placements' not in value and env.pin['node_id'] not in json.dumps(value)
    assert mode == 'warm' or hub._sessions == {}


@pytest.fixture
def wal(side, request):
    """Real committed WAL not checkpointed into DB; no cleanup/delete fixture."""
    origin = side.env.root / 'live-wal-origin'
    origin.mkdir()
    database = origin / 'autonomy.sqlite3'
    with database.open('xb') as stream:
        stream.write(side.before)
    writer = sqlite3.connect(database, isolation_level=None)
    image = side.env.root / 'retained-wal-image'
    image.mkdir()
    try:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('INSERT INTO metadata VALUES(?,?)',
                       ('readback_wal_fixture', json.dumps({'committed': 'WAL-not-main-DB'})))
        writer.execute('COMMIT')
        assert database.read_bytes()[18:20] == b'\x02\x02'
        assert Path(str(database) + '-wal').stat().st_size > 32
        assert Path(str(database) + '-shm').is_file()
        for suffix in ('', '-wal', '-shm'):
            if suffix == '-shm' and request.param == 'missing_shm':
                continue  # Never copied, not removed.
            with (image / ('autonomy.sqlite3' + suffix)).open('xb') as stream:
                stream.write(Path(str(database) + suffix).read_bytes())
        before = physical(image / 'autonomy.sqlite3')
        side.evidence.capture('live_WAL_and_retained_image_ready_' + request.param)
        yield SimpleNamespace(side=side, image=image, database=image / 'autonomy.sqlite3',
                              before=before, auxiliary=request.param)
    finally:
        # Capture before SQLite's ordinary owner close/checkpoint as well as
        # afterwards; no such lifecycle effects are counted as GET evidence.
        side.evidence.capture('WAL_owner_before_close')
        writer.close()
        side.evidence.capture('WAL_owner_after_close')


def wal_swap(wal, kind):
    side = wal.side
    target = side.env.a.store.path
    state = {'done': False, 'retained': None, 'tree_at_swap': None}

    def swap():
        assert not state['done']
        state['done'] = True
        side.evidence.capture('before_real_WAL_' + kind + '_replacement')
        if kind == 'directory':
            retained = side.env.root / 'retained-original-control'
            side.env.a.directory.rename(retained)
            wal.image.rename(side.env.a.directory)
            state['retained'] = retained / 'autonomy.sqlite3'
        else:
            retained = side.env.root / 'retained-original.sqlite3'
            target.rename(retained)
            state['retained'] = retained
            for suffix in ('-wal', '-shm'):
                original_auxiliary = Path(str(target) + suffix)
                if original_auxiliary.exists():
                    original_auxiliary.rename(Path(str(retained) + suffix))
            for suffix in ('', '-wal', '-shm'):
                path = Path(str(wal.database) + suffix)
                if path.exists():
                    assert not Path(str(target) + suffix).exists()
                    path.rename(Path(str(target) + suffix))
        state['tree_at_swap'] = side.evidence.capture('after_real_WAL_replacement_before_open')

    return swap, state


def assert_same_tree(before, after, evidence, shm=None):
    changed = [key for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]
    print(json.dumps({'tree_changes': changed, 'retained_evidence': str(evidence.directory)}, sort_keys=True))
    if shm is not None:
        # Signed V11 WAL-aux: only this database's -shm may change, and it must
        # remain a regular file. Creating a missing -shm may change only its
        # directory's entry count and times.
        folder = shm.rpartition('/')[0]
        shm_file = after.get(shm, {}).get('kind') == 'file'
        def entry(tree):
            return {k: v for k, v in tree[folder].items() if k not in ('nlink', 'mtime_ns', 'ctime_ns')}
        created = shm_file and shm not in before and folder in before and folder in after \
            and entry(before) == entry(after)
        changed = [key for key in changed
                   if not (shm_file and key == shm) and not (created and key == folder)]
    assert not changed, 'read changed real WAL/shm or full fixture tree: ' + ', '.join(changed)


@pytest.mark.parametrize('wal', ['existing_shm', 'missing_shm'], indirect=True)
@pytest.mark.parametrize('kind', ['database', 'directory'])
@pytest.mark.parametrize('phase', ['approval_open', 'snapshot_open'])
@pytest.mark.parametrize('mode', ['warm', 'cold'])
def test_real_wal_substitution_get_has_zero_tree_effects(wal, monkeypatch, kind, phase, mode):
    """Strict zero-tree candidate oracle; retain any auxiliary-rights conflict."""
    side, target = wal.side, wal.side.env.a.store.path
    hub = side.env.h if mode == 'warm' else console.MissionHub(side.env.h.directory)
    raw_connect = sqlite3.connect
    swap, state = wal_swap(wal, kind)
    opens, observed_trees, statements = [], [], []
    swap_index = 1 if phase == 'approval_open' else 2

    def observe(label):
        tree = side.evidence.capture(label)
        if state['done']:
            observed_trees.append(tree)

    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            try:
                statements.append((self.index, sql))
                return super().execute(sql, parameters)
            finally:
                observe(f'connection_{self.index}_' + sql)

        def close(self):
            observe(f'before_connection_{self.index}_close')
            try:
                return super().close()
            finally:
                observe(f'after_connection_{self.index}_close')

    def connect(path, *args, **kwargs):
        text = str(path)
        if text != str(target) and not text.startswith(target.as_uri() + '?'):
            return raw_connect(path, *args, **kwargs)
        opens.append(text)
        index = len(opens)
        if index == swap_index:
            swap()
        assert 'factory' not in kwargs
        try:
            db = raw_connect(path, *args, factory=Connection, **kwargs)
        except Exception:
            observe('open_error')
            raise
        db.index = index
        observe(f'after_connection_{index}_open')
        return db

    with monkeypatch.context() as guard:
        read_guard(hub, guard)
        guard.setattr(console.sqlite3, 'connect', connect)
        side.evidence.capture('before_real_WAL_get')
        code, value = call(hub, '/api/missions/' + side.env.ident + '/placements')
    tree_after = side.evidence.capture('after_real_WAL_get')
    print(json.dumps({'mode': mode, 'phase': phase, 'kind': kind, 'auxiliary': wal.auxiliary,
                      'status': code, 'error': value.get('error'), 'sql': statements}, sort_keys=True))
    assert state['done'] and state['retained'].is_file()
    assert len(opens) == swap_index
    assert code == 403 and value['error']['type'] == 'PermissionError'
    assert 'placements' not in value and side.env.pin['node_id'] not in json.dumps(value)
    assert mode == 'warm' or hub._sessions == {}
    # V11 WAL-aux: approved_spec's read (approval_open) may sync -shm; snapshot_open stays strict.
    shm = Path(str(target) + '-shm').relative_to(side.evidence.root).as_posix() \
        if phase == 'approval_open' else None
    assert_same_tree(state['tree_at_swap'], tree_after, side.evidence, shm)
    for tree in observed_trees:
        assert_same_tree(state['tree_at_swap'], tree, side.evidence, shm)


@pytest.mark.parametrize('wal', ['existing_shm', 'missing_shm'], indirect=True)
def test_actual_uri_ro_live_wal_reads_current_commit_and_rejects_main_database_write(wal):
    side, database = wal.side, wal.database
    before = physical(database)
    side.evidence.capture('before_URI_ro_WAL_database_permission_proof')
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, isolation_level=None)
    try:
        db.execute('BEGIN')
        row = db.execute("SELECT value FROM metadata WHERE key='readback_wal_fixture'").fetchone()
        assert json.loads(row[0]) == {'committed': 'WAL-not-main-DB'}, 'current WAL frames were lost'
        side.evidence.capture('URI_ro_WAL_current_commit_read')
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute("UPDATE metadata SET value='wrong' WHERE key='native_worker_spec'")
        db.execute('COMMIT')
    finally:
        db.close()
        side.evidence.capture('after_URI_ro_WAL_database_permission_proof')
    after = physical(database)
    assert after['db'] == before['db'] and after['-wal'] == before['-wal']


@pytest.mark.parametrize('kind', ['missing_database', 'empty_directory', 'foreign_rollback'])
def test_actual_same_database_uri_ro_primitive_has_no_create_or_header_mutation(side, kind):
    """Kernel primitive proof only; production method/hook remains unchanged."""
    target = side.env.a.store.path
    swap, state = real_swap(side, kind)
    swap()
    observations = []
    if kind in ('missing_database', 'empty_directory'):
        with pytest.raises(sqlite3.OperationalError):
            sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, isolation_level=None)
        observations.append(('mode_ro_open_error', physical(target)))
    else:
        db = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN')
            row = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
            assert json.loads(row['value']) == side.env.b.spec
            assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
            observations.append(('mode_ro_snapshot', physical(target)))
            db.execute('COMMIT')
        finally:
            db.close()
    assert_no_side_effect(side, kind, state, observations)
