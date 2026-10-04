#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def project_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if not match:
        raise SystemExit("pyproject.toml has no project version")
    return match.group(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist")
    parser.add_argument(
        "--repository", default="DionisAI/sisyfus-skill"
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    version = project_version(root)
    tag = f"v{version}"
    ref = os.environ.get("GITHUB_REF_NAME") or tag
    if ref != tag:
        raise SystemExit(
            f"release tag {ref!r} does not match package {tag!r}"
        )

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    output = (root / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"sisyfus-{version}.tar.gz"
    prefix = f"sisyfus-{version}/"
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            f"--prefix={prefix}",
            "-o",
            str(archive),
            "HEAD",
        ],
        cwd=root,
        check=True,
    )
    digest = sha256(archive)
    manifest = {
        "schema_version": "sisyfus.release.v1",
        "repository": args.repository,
        "version": version,
        "tag": tag,
        "commit_sha": commit,
        "archive_name": archive.name,
        "archive_sha256": digest,
        "minimum_python": "3.11",
        "autonomy_schema_version": 2,
        "breaking": False,
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
