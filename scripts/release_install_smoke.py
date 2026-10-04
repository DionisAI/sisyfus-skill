"""Install the just-built source archive and exercise all installed CLI routes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.dist / 'release-manifest.json').read_text())
    archive = args.dist / manifest['archive_name']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive_sha256']
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'HOME': str(root / 'home'), 'SISYFUS_ENGINE_HOME': str(root / 'engine'),
           'SISYFUS_BIN_DIR': str(root / 'bin'), 'SISYFUS_SKILL_DIRS': str(root / 'skills'),
           'SISYFUS_AUTO_SERVE': '0', 'SISYFUS_AUTO_OPEN': '0'}
    from sisyfus.updater import _safe_extract
    source = _safe_extract(archive, root / 'unpacked')
    subprocess.run(['bash', str(source / 'install.sh')], env=env, check=True, timeout=60)
    executable = str(root / 'bin' / 'sisyfus')
    def run(*command: str) -> str:
        return subprocess.check_output([executable, *command], env=env, text=True, timeout=60)
    assert run('--version').strip() == manifest['version']
    for route in ('workers', 'os', 'update'):
        run(route, '--help')
    report = json.loads(run('workers', 'demo', '--directory', str(root / 'demo')))
    assert report['all_verified'] and report['native_call_reservations'] == 4 and not report['unresolved']
    # Fresh interpreter checks the activated release after workers imports and runs.
    code = ('from sisyfus.updater import InstallLayout,_verify_release; '
            'p=InstallLayout.discover().current_link.resolve(); '
            'assert _verify_release(p)["complete"]')
    installed = root / 'engine' / 'current' / 'lib'
    subprocess.run([sys.executable, '-I', '-S', '-c',
                    'import sys;sys.dont_write_bytecode=True;sys.path.insert(0,' + repr(str(installed.resolve())) + ');' + code],
                   env=env, check=True, timeout=60)
    result = {'source_commit': manifest['commit_sha'], 'archive_sha256': manifest['archive_sha256'],
              'installed_version': manifest['version'], 'workers_os_update_routes': True,
              'installed_demo_passed': True, 'real_llm_executed': False,
              'post_run_install_integrity_verified': True}
    (args.dist / 'install-validation.json').write_text(json.dumps(result, indent=2) + '\n')

if __name__ == '__main__':
    main()
