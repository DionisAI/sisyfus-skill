"""Private password-verifier setup; no controller, network, session or native work.

Passwords are prompt-only inputs, never serialized. Public file primitives keep
failed/new files and reject links, changing identities and attacker-selected KDF
costs. The separate Gateway owns session admission and lifetime.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

_SCHEMA = "sisyfus.share.password.v1"
_FIELDS = {"schema", "kdf", "n", "r", "p", "salt", "digest"}
_N, _R, _P, _MAXMEM, _DKLEN = 131072, 8, 1, 268435456, 32
_LIMIT = 4096
_TYPES = {c: c.__name__ for c in (
    Exception, RuntimeError, ValueError, TypeError, OSError, PermissionError, FileNotFoundError,
    FileExistsError, NotADirectoryError, IsADirectoryError, EOFError,
    UnicodeDecodeError, KeyboardInterrupt,
)}


def _password_bytes(password):
    if (type(password) is not str or not 12 <= len(password) <= 128
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in password)):
        raise ValueError("password shape")
    raw = password.encode("utf-8")
    if len(raw) > 512:
        raise ValueError("password byte limit")
    return raw


def _derive(raw, salt):
    return hashlib.scrypt(raw, salt=salt, n=_N, r=_R, p=_P,
                          maxmem=_MAXMEM, dklen=_DKLEN)


def create_verifier(password):
    """Return a fresh fixed-cost scrypt verifier; reject invalid plaintext unchanged."""
    raw = _password_bytes(password)
    salt = secrets.token_bytes(16)
    digest = _derive(raw, salt)
    return {"schema": _SCHEMA, "kdf": "scrypt", "n": _N, "r": _R,
            "p": _P, "salt": salt.hex(), "digest": digest.hex()}


def validate_verifier(value):
    """Return an independent strict copy; no coercion, extra fields or variable costs."""
    if type(value) is not dict or any(type(k) is not str for k in value) or set(value) != _FIELDS:
        raise ValueError("verifier fields")
    if (type(value["schema"]) is not str or value["schema"] != _SCHEMA
            or type(value["kdf"]) is not str or value["kdf"] != "scrypt"):
        raise ValueError("verifier schema")
    for key, expected in (("n", _N), ("r", _R), ("p", _P)):
        if type(value[key]) is not int or value[key] != expected:
            raise ValueError("verifier costs")
    for key, length in (("salt", 32), ("digest", 64)):
        if type(value[key]) is not str or re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value[key]) is None:
            raise ValueError("verifier encoding")
    return dict(value)


def verify_password(password, value):
    """Compare actual fixed-cost scrypt bytes in constant time; valid wrong input is False."""
    raw = _password_bytes(password)
    verifier = validate_verifier(value)
    digest = _derive(raw, bytes.fromhex(verifier["salt"]))
    return hmac.compare_digest(digest, bytes.fromhex(verifier["digest"]))


def _absolute(path):
    text = os.fspath(path)
    if (not isinstance(text, str) or not text or not os.path.isabs(text)
            or text.startswith("//") or "\0" in text
            or any(part in {".", ".."} for part in text.split("/"))):
        raise ValueError("absolute verifier file")
    result = Path(text)
    if not result.name:
        raise ValueError("verifier file name")
    return result


def _parent(path):
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    chain = []
    try:
        for part in ("/", *path.parts[1:-1]):
            if part != "/":
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            info = os.fstat(fd)
            chain.append((info.st_dev, info.st_ino))
        return fd, tuple(chain)
    except BaseException:
        os.close(fd)
        raise


def _info(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size > _LIMIT:
        raise ValueError("bounded regular verifier")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        raise PermissionError("private verifier ownership")
    return info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _visible(path, chain, fd=None):
    """Reopen the full NOFOLLOW chain; a pinned but detached directory is not visible."""
    parent, current_chain = _parent(path)
    try:
        if current_chain != chain:
            raise RuntimeError("verifier parent changed")
        if fd is not None:
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if _identity(current) != _identity(_info(fd)):
                raise RuntimeError("verifier identity changed")
    finally:
        os.close(parent)


def _read(fd, size):
    chunks = []
    left = size + 1
    while left:
        chunk = os.read(fd, min(left, _LIMIT + 1))
        if not chunk:
            break
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate verifier field")
        result[key] = value
    return result


def save_verifier(path, value):
    """Exclusively create a private verifier; return None, retaining partial failures.

    Never mkdir, chmod, replace or remove. File and full parent identities are
    checked around writes/readback; existing paths and input value are untouched.
    """
    verifier = validate_verifier(value)
    target = _absolute(path)
    payload = (json.dumps(verifier, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    parent, chain = _parent(target)
    try:
        _visible(target, chain)
        fd = os.open(target.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        _info(fd)
        _visible(target, chain, fd)
        view = memoryview(payload)
        while view:
            _visible(target, chain, fd)
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("verifier write")
            view = view[count:]
        os.fsync(fd)
        before = _info(fd)
        if before.st_size != len(payload):
            raise RuntimeError("verifier write size")
        os.lseek(fd, 0, os.SEEK_SET)
        if _read(fd, before.st_size) != payload or _identity(before) != _identity(_info(fd)):
            raise RuntimeError("verifier write changed")
        _visible(target, chain, fd)
    finally:
        os.close(fd)


def load_verifier(path):
    """Read <=4096 private regular bytes; validate fd/visible identities before+after.

    No link following, FIFO reads, coercion or directory creation. Any malformed
    payload or changed byte/parent/file identity fails rather than accepting data.
    """
    target = _absolute(path)
    parent, chain = _parent(target)
    try:
        fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = _info(fd)
        _visible(target, chain, fd)
        raw = _read(fd, before.st_size)
        if len(raw) != before.st_size or _identity(before) != _identity(_info(fd)):
            raise RuntimeError("verifier read changed")
        _visible(target, chain, fd)
    finally:
        os.close(fd)
    return validate_verifier(json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs))


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("setup arguments")


class _Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise ValueError("duplicate output flag")
        setattr(namespace, self.dest, values)


def main(argv=None, *, get_password=None):
    """Two hidden prompts -> new private file; help0/error1/interrupt130, no secret output."""
    stage = "parse"
    try:
        parser = _Parser(prog="python -m sisyfus.workers.share_password", allow_abbrev=False, add_help=False)
        parser.add_argument("-h", "--help", action="store_true")
        parser.add_argument("--output", action=_Once)
        args = parser.parse_args(argv)
        if args.help:
            parser.print_help()
            return 0
        target = _absolute(args.output)
        if get_password is None:
            from getpass import GetPassWarning, getpass
            import warnings
            def get_password(prompt):
                with warnings.catch_warnings():
                    warnings.simplefilter("error", GetPassWarning)
                    return getpass(prompt)
        stage = "password.first"
        password = get_password("访问密码：")
        stage = "password.confirm"
        confirm = get_password("再次输入访问密码：")
        if type(password) is not str or type(confirm) is not str or password != confirm:
            raise ValueError("password confirmation")
        stage = "password.validate"
        _password_bytes(password)
        stage = "verifier.create"
        verifier = create_verifier(password)
        stage = "verifier.save"
        save_verifier(target, verifier)
        print(json.dumps({"status": "CREATED", "verifier_file": str(target)}, ensure_ascii=False), flush=True)
        return 0
    except BaseException as exc:
        print(json.dumps({"status": "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "ERROR",
                          "stage": stage, "error_type": _TYPES.get(type(exc), "Exception")}), file=sys.stderr, flush=True)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
