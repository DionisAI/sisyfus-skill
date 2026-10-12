"""Node-local v1 transport journal, not controller acceptance or execution truth.

All native reservations precede accessing the driver. Unknown reservations are
never relaunched. Files, failed attempts and transport records remain retained.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
import fcntl
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import stat
import threading
import time
from urllib.parse import urlencode

from .codex import CodexDriver
from .node_claims import (_control_payload, _receipt_payload, _sync_batch,
                          _transport_manifest, _tree_payload)
from .protocol import Receipt, Request, bounded, digest, environment, redact
from .remote_artifacts import full_tree_manifest


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_IDENTITY = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_NODE = re.compile(r"node_[0-9a-f]{32}\Z")
_CLAIM = re.compile(r"claim_[0-9a-f]{32}\Z")
_NAMESPACE = re.compile(r"mission_[0-9a-f]{32}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_HOST = re.compile(r"(127\.0\.0\.1|localhost):([1-9][0-9]{0,4})\Z")
_ERROR_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_IMMUTABLE = ("mission_id", "run_key", "node_id", "task_id", "driver", "request",
              "prompt_hash", "input_manifest", "input_manifest_hash")
_MAX_REQUEST_JSON = 1_500_000
_MAX_RESPONSE = 4_000_000
_MAX_ERROR_RESPONSE = 16_384
_MAX_OUTBOX_COUNT = 10_000
_MAX_OUTBOX_BYTES = 32_000_000
_HEARTBEAT_RETRY_SECONDS = 2.0


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        # The N1 validator bounds nesting and disallows unsupported JSON types.
        from .node_claims import _sync_json
        _sync_json(value)
        return value
    except (UnicodeError, RecursionError, TypeError) as exc:
        raise ValueError("invalid bounded JSON") from exc


def _open_directory(path, *, ancestors=None):
    """Pin every component; no symlink ancestors or relative parent traversal."""
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("directory parent traversal")
    fd = os.open("/", _DIR_FLAGS)
    try:
        if ancestors is not None:
            info = os.fstat(fd)
            ancestors.add((info.st_dev, info.st_ino))
        for part in path.parts[1:]:
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
            if ancestors is not None:
                info = os.fstat(fd)
                ancestors.add((info.st_dev, info.st_ino))
        return fd
    except BaseException:
        os.close(fd)
        raise


def _regular(info, *, private=False):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("regular single-link file required")
    if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("file requires current owner and exact 0600")


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _GatewayError(RuntimeError):
    def __init__(self, status, message, *, error_type=None):
        self.status = status
        self.error_type = error_type
        if error_type is not None:
            message += " (" + error_type + ")"
        super().__init__(f"gateway HTTP {status}: {message}")

    @property
    def authority_lost(self):
        return self.status in {401, 403} or self.status == 409 and self.error_type == "LeaseLost"


class NodeAgent:
    """One operator-configured node; construction does no network or probing."""

    def __init__(self, credential_file, state_directory, *, driver=None):
        self._root_fd = None
        self._secret = ""
        self._mutex = threading.Lock()
        self._db_mutex = threading.RLock()
        self.state_directory = Path(state_directory).absolute()
        credential = Path(credential_file).absolute()
        try:
            credential_ancestors = set()
            parent = _open_directory(credential.parent, ancestors=credential_ancestors)
            try:
                fd = os.open(credential.name, _FILE_FLAGS, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    _regular(before, private=True)
                    if before.st_size > 16_384:
                        raise ValueError("credential size exceeds bound")
                    raw = os.read(fd, 16_385)
                    if len(raw) != before.st_size or _stamp(os.fstat(fd)) != _stamp(before):
                        raise ValueError("credential changed during read")
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
            config = _json(raw)
            names = {"schema", "controller_mission_id", "node_id", "secret", "gateway_url", "gateway_host"}
            schema2 = (isinstance(config, dict) and type(config.get("schema")) is int
                       and config["schema"] == 2)
            if schema2:
                names = names | {"heartbeat_timeout_seconds"}
            if not isinstance(config, dict) or set(config) != names:
                raise ValueError("credential fields differ from v1")
            if type(config["schema"]) is not int or config["schema"] != (2 if schema2 else 1):
                raise ValueError("unsupported credential schema")
            if schema2:
                bounded(config["heartbeat_timeout_seconds"], 0.4, 1.0, "heartbeat timeout")
            if any(not isinstance(config[key], str) for key in names - {"schema", "heartbeat_timeout_seconds"}):
                raise ValueError("credential string field type")
            if not _HEX.fullmatch(config["secret"]):
                raise ValueError("invalid node secret")
            self._secret = config["secret"]
            if self._secret in str(self.state_directory):
                raise ValueError("state path contains node credential material")
            if not _NODE.fullmatch(config["node_id"]) or not _IDENTITY.fullmatch(config["controller_mission_id"]):
                raise ValueError("invalid configured node/controller identity")
            url = config["gateway_url"]
            connect = _HOST.fullmatch(url[7:]) if url.startswith("http://") else None
            host = _HOST.fullmatch(config["gateway_host"])
            if connect is None or host is None or int(connect[2]) > 65535 or int(host[2]) > 65535:
                raise ValueError("fixed loopback URL and actual Host/port required")
            if credential.is_relative_to(self.state_directory):
                raise ValueError("credentials must be outside state/workspaces")
            self.controller_mission_id = config["controller_mission_id"]
            self.node_id = config["node_id"]
            self._connect_host, self._connect_port = connect[1], int(connect[2])
            self._gateway_host = config["gateway_host"]
            self._prefix = "/node/v1/" + self.controller_mission_id
            self._heartbeat_timeout_seconds = config["heartbeat_timeout_seconds"] if schema2 else 0.4
            # Neither credentials nor secret are retained in the local database.
            self._configuration = {key: config[key] for key in names - {"secret"}}
            if self._secret.encode() in _encoded(self._configuration):
                raise ValueError("configured public fields contain node credential material")
        except Exception as exc:
            # Parse errors may quote an unparsed secret. Never echo raw config.
            raise ValueError(f"invalid node credential configuration ({type(exc).__name__})") from None

        parent = _open_directory(self.state_directory.parent)
        try:
            try:
                os.mkdir(self.state_directory.name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            self._root_fd = os.open(self.state_directory.name, _DIR_FLAGS, dir_fd=parent)
            os.fsync(parent)
            info = os.fstat(self._root_fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("state root requires current owner and exact 0700")
            self._root_identity = (info.st_dev, info.st_ino)
            if self._root_identity in credential_ancestors:
                raise ValueError("credentials must be outside state/workspaces")
        finally:
            os.close(parent)
        self._db_path = self.state_directory / "agent.sqlite3"
        with self._exclusive():
            for name in ("agent.sqlite3", "agent.sqlite3-journal"):
                fd = self._private_file(name)
                try:
                    info = os.fstat(fd)
                    if name == "agent.sqlite3":
                        self._db_identity = (info.st_dev, info.st_ino)
                    else:
                        self._journal_identity = (info.st_dev, info.st_ino)
                finally:
                    os.close(fd)
            workspace_root = self._private_directory("workspaces")
            if tuple(workspace_root) in credential_ancestors:
                raise ValueError("credentials must be outside state/workspaces")
            with self._db() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS configuration (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS attempts (
                        request_id TEXT PRIMARY KEY, status TEXT NOT NULL, offer TEXT,
                        workspace TEXT, receipt TEXT, tree TEXT, receipt_body TEXT,
                        ack INTEGER NOT NULL DEFAULT 0, lease_lost INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE IF NOT EXISTS outbox (
                        request_id TEXT NOT NULL, seq INTEGER NOT NULL, event TEXT NOT NULL,
                        PRIMARY KEY(request_id,seq));
                    CREATE TABLE IF NOT EXISTS uploads (
                        request_id TEXT NOT NULL, path TEXT NOT NULL, metadata TEXT NOT NULL,
                        bytes BLOB NOT NULL, stored INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(request_id,path));
                    CREATE TABLE IF NOT EXISTS controls (
                        request_id TEXT NOT NULL, id TEXT NOT NULL, control TEXT NOT NULL,
                        delivered INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(request_id,id));
                    CREATE TABLE IF NOT EXISTS diagnostics (
                        id INTEGER PRIMARY KEY, request_id TEXT, message TEXT NOT NULL);
                """)
                fixed = _encoded(self._configuration).decode()
                previous = db.execute("SELECT value FROM configuration WHERE key='identity'").fetchone()
                if previous and previous[0] != fixed:
                    raise ValueError("state belongs to another fixed configuration")
                db.execute("INSERT OR IGNORE INTO configuration VALUES('identity',?)", (fixed,))
                root_pin = _encoded(workspace_root).decode()
                old = db.execute("SELECT value FROM configuration WHERE key='workspace_root'").fetchone()
                if old is not None and old[0] != root_pin:
                    raise ValueError("persistent workspace root identity changed")
                db.execute("INSERT OR IGNORE INTO configuration VALUES('workspace_root',?)", (root_pin,))
        self.driver = CodexDriver() if driver is None else driver

    def __del__(self):
        fd = getattr(self, "_root_fd", None)
        if fd is not None:
            os.close(fd)
            self._root_fd = None

    def _clean(self, value):
        if isinstance(value, str):
            return value.replace(self._secret, "[REDACTED]")
        if isinstance(value, dict):
            return {self._clean(key): self._clean(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self._clean(child) for child in value]
        return value

    def _check_root(self):
        fd = _open_directory(self.state_directory)
        try:
            info = os.fstat(fd)
            if ((info.st_dev, info.st_ino) != self._root_identity or
                    info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise ValueError("state directory identity changed")
        finally:
            os.close(fd)

    def _private_directory(self, name):
        try:
            os.mkdir(name, 0o700, dir_fd=self._root_fd)
            os.fsync(self._root_fd)
        except FileExistsError:
            pass
        fd = os.open(name, _DIR_FLAGS, dir_fd=self._root_fd)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("private directory permissions changed")
            return [info.st_dev, info.st_ino]
        finally:
            os.close(fd)

    def _private_file(self, name):
        try:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._root_fd)
            os.fsync(self._root_fd)
        except FileExistsError:
            fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._root_fd)
        try:
            _regular(os.fstat(fd), private=True)
        except BaseException:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def _exclusive(self):
        if not self._mutex.acquire(blocking=False):
            raise RuntimeError("node agent already running")
        fd = None
        try:
            self._check_root()
            fd = self._private_file("agent.lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("another node agent owns this state") from None
            yield
        finally:
            if fd is not None:
                os.close(fd)
            self._mutex.release()

    @contextmanager
    def _db(self):
        if not self._db_mutex.acquire(timeout=0.5):
            raise RuntimeError("local transport transaction lock timeout")
        db, pinned = None, []
        try:
            def check_pins():
                self._check_root()
                for name, fd, identity in pinned:
                    info = os.fstat(fd)
                    _regular(info, private=True)
                    current = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
                    _regular(current, private=True)
                    if (info.st_dev, info.st_ino) != identity or (current.st_dev, current.st_ino) != identity:
                        raise ValueError("local database/sidecar inode changed")
                for name in ("agent.sqlite3-wal", "agent.sqlite3-shm"):
                    try:
                        os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    raise ValueError("unexpected retained SQLite WAL/SHM sidecar; reconciliation required")

            for name, identity in (("agent.sqlite3", self._db_identity),
                                   ("agent.sqlite3-journal", self._journal_identity)):
                fd = os.open(name, _FILE_FLAGS, dir_fd=self._root_fd)
                pinned.append((name, fd, identity))
            check_pins()
            # PERSIST keeps the rollback journal; no unlink/cleanup dependency.
            # mode=rw forbids silently recreating a missing, exchanged database.
            db = sqlite3.connect(self._db_path.as_uri() + "?mode=rw", uri=True, timeout=0.5)
            check_pins()
            db.row_factory = sqlite3.Row
            if db.execute("PRAGMA journal_mode=PERSIST").fetchone()[0].lower() != "persist":
                raise ValueError("local database requires retained PERSIST journal")
            db.execute("PRAGMA synchronous=FULL")
            check_pins()
            db.execute("BEGIN IMMEDIATE")
            yield db
            check_pins()
            db.commit()
            check_pins()
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()
            for _, fd, _ in pinned:
                os.close(fd)
            self._db_mutex.release()

    def _diagnostic(self, request_id, message):
        safe = self._clean(str(message))[:2000]
        with self._db() as db:
            db.execute("INSERT INTO diagnostics(request_id,message) VALUES(?,?)", (request_id, safe))

    def _attempt(self, request_id):
        with self._db() as db:
            return dict(db.execute("SELECT * FROM attempts WHERE request_id=?", (request_id,)).fetchone())

    def _update(self, request_id, **changes):
        allowed = {"status", "offer", "workspace", "receipt", "tree", "receipt_body", "ack", "lease_lost"}
        if not changes or set(changes) - allowed:
            raise ValueError("invalid local transport update")
        with self._db() as db:
            db.execute("UPDATE attempts SET " + ",".join(key + "=?" for key in changes) + " WHERE request_id=?",
                       (*changes.values(), request_id))

    def _call(self, operation, body=None, *, offer=None, path=None, data=None, sha=None):
        binary = operation == "inputs"
        route = self._prefix + "/" + operation
        method = "POST"
        if operation in {"inputs", "uploads"}:
            route += "/" + offer["claim_id"] + "/" + str(offer["epoch"])
            query = {"path": path}
            if sha is not None:
                query["sha256"] = sha
            route += "?" + urlencode(query)
            method = "GET" if binary else "PUT"
        payload = data if data is not None else _encoded(body) if body is not None else b""
        if self._secret.encode() in payload:
            raise ValueError("transport data contains node credential material")
        if len(payload) > (8_000_000 if operation == "uploads" else _MAX_REQUEST_JSON):
            raise ValueError("transport request exceeds bound")
        duration = self._heartbeat_timeout_seconds if operation == "heartbeat" else 2
        deadline = time.monotonic() + duration
        # Both permitted URL hosts name this fixed IPv4 loopback gateway. Avoid
        # resolver latency/host selection; the configured actual Host is separate.
        connection = http.client.HTTPConnection("127.0.0.1", self._connect_port, timeout=duration)
        sock, pinned_socket, response = None, None, None
        expired = threading.Event()

        def abort():
            expired.set()
            if pinned_socket is not None:
                try:
                    pinned_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                pinned_socket.close()

        def remaining():
            left = deadline - time.monotonic()
            if expired.is_set() or left <= 0:
                raise TimeoutError("gateway aggregate wall-clock deadline exceeded")
            # HTTP/1.0 may close the response socket at the exact final byte.
            # Deadline checks still apply after EOF, but no socket remains to tune.
            if sock is not None and sock.fileno() >= 0:
                sock.settimeout(left)

        # A per-recv timeout alone permits indefinite slow-drip headers. The
        # independent shutdown bounds header parsing, sendall and body reads too.
        watchdog = threading.Timer(duration, abort)
        watchdog.daemon = True
        watchdog.start()
        try:
            connection.connect()
            sock = connection.sock
            # HTTPConnection detaches/closes its socket object for Connection:
            # close while HTTPResponse still owns a fileobject reference. A
            # separate descriptor keeps watchdog shutdown effective throughout.
            pinned_socket = sock.dup()
            remaining()
            connection.putrequest(method, route, skip_host=True, skip_accept_encoding=True)
            for key, value in {"Host": self._gateway_host, "Authorization": "Node " + self._secret,
                               "X-Sisyfus-Node": self.node_id, "Content-Length": str(len(payload)),
                               "Content-Type": "application/octet-stream" if data is not None else "application/json"}.items():
                connection.putheader(key, value)
            connection.endheaders(payload)
            remaining()
            response = connection.getresponse()
            remaining()
            lengths = [value for key, value in response.getheaders() if key.lower() == "content-length"]
            if len(lengths) != 1 or not lengths[0].isdigit() or response.getheader("Transfer-Encoding") is not None:
                raise ValueError("gateway response requires one fixed Content-Length")
            length = int(lengths[0])
            if response.status != 200 and length > _MAX_ERROR_RESPONSE:
                raise _GatewayError(response.status, "error response exceeds bound")
            if length > (8_000_000 if binary else _MAX_RESPONSE):
                raise ValueError("gateway response exceeds bound")
            chunks, count = [], 0
            while count < length:
                remaining()
                chunk = response.read1(min(65536, length - count))
                remaining()
                if not chunk:
                    raise ValueError("gateway response body length mismatch")
                chunks.append(chunk)
                count += len(chunk)
            raw = b"".join(chunks)
            remaining()
            if len(raw) != length:
                raise ValueError("gateway response body length mismatch")
            if response.status != 200:
                error_type = None
                try:
                    envelope = _json(raw)
                    error = envelope.get("error") if isinstance(envelope, dict) else None
                    if (isinstance(envelope, dict) and set(envelope) == {"error"}
                            and isinstance(error, dict) and {"type", "message"} <= set(error)
                            and not set(error) - {"type", "message", "diagnostic_id"}
                            and isinstance(error["message"], str)
                            and ("diagnostic_id" not in error or isinstance(error["diagnostic_id"], str))
                            and isinstance(error["type"], str) and _ERROR_TYPE.fullmatch(error["type"])
                            and self._clean(redact(error["type"])) == error["type"]):
                        error_type = error["type"]
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    pass  # An invalid envelope preserves an unknown HTTP error.
                # Never echo untrusted response bodies, messages or credentials.
                raise _GatewayError(response.status,
                    "redirect rejected" if 300 <= response.status < 400 else "operation rejected",
                    error_type=error_type)
            if self._secret.encode() in raw:
                raise ValueError("gateway response contains node credential material")
            if binary:
                return raw
            envelope = _json(raw)
            permitted = {"controller_mission_id", "result"} | ({"controls"} if operation == "heartbeat" else set())
            if (not isinstance(envelope, dict) or not {"controller_mission_id", "result"} <= set(envelope)
                    or set(envelope) - permitted or envelope["controller_mission_id"] != self.controller_mission_id):
                raise ValueError("gateway controller envelope identity mismatch")
            if not isinstance(envelope["result"], dict):
                raise ValueError("gateway result must be an object")
            remaining()
            return envelope
        except TimeoutError:
            # The per-recv socket timeout and the watchdog share one deadline;
            # whichever expires first, report the same aggregate deadline.
            if expired.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("gateway aggregate wall-clock deadline exceeded") from None
            raise
        finally:
            watchdog.cancel()
            if response is not None:
                response.close()
            connection.close()
            if pinned_socket is not None:
                pinned_socket.close()
            watchdog.join(0.1)

    def _validate_offer(self, value, *, original=None):
        required = set(_IMMUTABLE) | {"fingerprint", "status", "claim_id", "epoch", "lease_expires_at",
                                     "created_at", "receipt", "manifest", "uploads"}
        if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"tree"}:
            raise ValueError("invalid public offer fields")
        if (not _NAMESPACE.fullmatch(str(value["mission_id"])) or value["node_id"] != self.node_id
                or not _CLAIM.fullmatch(str(value["claim_id"])) or type(value["epoch"]) is not int or value["epoch"] != 1):
            raise ValueError("offer namespace/node/claim/epoch identity mismatch")
        if not isinstance(value["run_key"], str) or not 1 <= len(value["run_key"].encode()) <= 200:
            raise ValueError("invalid offer run identity")
        raw = value["request"]
        if not isinstance(raw, dict) or set(raw) != {field.name for field in fields(Request)}:
            raise ValueError("offer requires exact original Request fields")
        if any(not isinstance(raw[key], str) or not raw[key].strip() for key in ("task_id", "prompt", "cwd", "model", "mode")):
            raise ValueError("invalid Request text fields")
        if (value["task_id"] != raw["task_id"] or value["driver"] != "codex" or raw["model"] != "gpt-6.1-sol"
                or raw["mode"] != "workspace-write" or raw["session_id"] is not None):
            raise ValueError("offer task/model/mode identity mismatch")
        if not Path(raw["cwd"]).is_absolute() or ".." in Path(raw["cwd"]).parts or len(raw["prompt"].encode()) > 200_000:
            raise ValueError("invalid original cwd/prompt bound")
        bounded(raw["timeout"], .05, 7200, "native timeout")
        if type(raw["max_output_bytes"]) is not int:
            raise ValueError("invalid native output limit")
        bounded(raw["max_output_bytes"], 1024, 32_000_000, "native output")
        if raw["max_turns"] is not None:
            if type(raw["max_turns"]) is not int:
                raise ValueError("invalid native turn limit")
            bounded(raw["max_turns"], 1, 100, "native turns")
        manifest = _transport_manifest(value["input_manifest"])
        if manifest != value["input_manifest"] or digest(manifest) != value["input_manifest_hash"] or digest(raw["prompt"]) != value["prompt_hash"]:
            raise ValueError("offer input/prompt hash mismatch")
        immutable = {key: value[key] for key in _IMMUTABLE}
        if digest(immutable) != value["fingerprint"]:
            raise ValueError("offer fingerprint mismatch")
        if original is not None and any(value[key] != original[key] for key in (*_IMMUTABLE, "fingerprint", "claim_id", "epoch")):
            raise ValueError("offer changed original pinned identities")
        deadline = value["lease_expires_at"]
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise ValueError("invalid claim lease deadline")
        return value

    def _identity_body(self, offer):
        return {"claim_id": offer["claim_id"], "epoch": offer["epoch"]}

    def _heartbeat(self, request_id, offer):
        envelope = self._call("heartbeat", self._identity_body(offer))
        view = self._validate_offer(envelope["result"], original=offer)
        if view["status"] != "CLAIMED":
            raise _GatewayError(409, "inactive claim")
        commands = _control_payload(envelope.get("controls", []))
        with self._db() as db:
            for command in commands:
                fixed = _encoded(command).decode()
                old = db.execute("SELECT control FROM controls WHERE request_id=? AND id=?", (request_id, command["id"])).fetchone()
                if old and old[0] != fixed:
                    raise ValueError("interrupt identity conflicts with original control")
                db.execute("INSERT OR IGNORE INTO controls(request_id,id,control) VALUES(?,?,?)", (request_id, command["id"], fixed))
        return view["lease_expires_at"]

    def _lost(self, request_id, offer):
        control = {"id": "local_lease_" + offer["claim_id"], "action": "interrupt", "text": ""}
        with self._db() as db:
            db.execute("UPDATE attempts SET lease_lost=1 WHERE request_id=?", (request_id,))
            db.execute("INSERT OR IGNORE INTO controls(request_id,id,control) VALUES(?,?,?)",
                       (request_id, control["id"], _encoded(control).decode()))

    def _controls(self, request_id):
        with self._db() as db:
            pending = db.execute("SELECT id,control FROM controls WHERE request_id=? AND delivered=0 ORDER BY rowid LIMIT 100", (request_id,)).fetchall()
            for row in pending:
                db.execute("UPDATE controls SET delivered=1 WHERE request_id=? AND id=?", (request_id, row["id"]))
            result = [json.loads(row["control"]) for row in pending]
        return result

    def _emit(self, request_id, kind, data):
        try:
            # Validate the original emit before scrubbing, never truncate/drop it.
            _sync_batch([{"seq": 1, "kind": kind, "data": data}])
            clean = self._clean(redact(data))
            with self._db() as db:
                count, size = db.execute("SELECT count(*),COALESCE(sum(length(CAST(event AS BLOB))),0) FROM outbox WHERE request_id=?", (request_id,)).fetchone()
                event = {"seq": count + 1, "kind": kind, "data": clean}
                _sync_batch([event])
                if count >= _MAX_OUTBOX_COUNT or size + len(_encoded(event)) > _MAX_OUTBOX_BYTES:
                    raise ValueError("native outbox exceeds retained bound")
                db.execute("INSERT INTO outbox VALUES(?,?,?)", (request_id, event["seq"], _encoded(event).decode()))
        except Exception as exc:
            self._diagnostic(request_id, f"invalid native event {str(kind)[:128]}: {type(exc).__name__}: {exc}")
            raise ValueError(self._clean(f"invalid native event {str(kind)[:128]}: {exc}")[:2000]) from None

    def _sync(self, request_id, offer):
        while True:
            with self._db() as db:
                ack = db.execute("SELECT ack FROM attempts WHERE request_id=?", (request_id,)).fetchone()[0]
                rows = db.execute("SELECT event FROM outbox WHERE request_id=? AND seq>? ORDER BY seq LIMIT 100", (request_id, ack)).fetchall()
            if not rows:
                return
            batch, size = [], 2
            for row in rows:
                event = json.loads(row[0])
                length = len(_encoded(event)) + 1
                if size + length > 1_000_000:
                    break
                batch.append(event)
                size += length
            result = self._call("sync", self._identity_body(offer) | {"events": batch})["result"]
            expected = {key: offer[key] for key in ("mission_id", "run_key", "node_id", "claim_id", "epoch")}
            if (set(result) != set(expected) | {"last_seq", "lease_expires_at"}
                    or any(result[key] != value or type(result[key]) is not type(value) for key, value in expected.items())
                    or type(result["last_seq"]) is not int or result["last_seq"] != batch[-1]["seq"]
                    or isinstance(result["lease_expires_at"], bool)
                    or not isinstance(result["lease_expires_at"], (int, float))
                    or not math.isfinite(result["lease_expires_at"])):
                raise ValueError("sync ACK identity/watermark mismatch; outbox remains unacknowledged")
            with self._db() as db:
                db.execute("UPDATE attempts SET ack=? WHERE request_id=?", (result["last_seq"], request_id))

    def _workspace_fd(self, workspace):
        self._check_root()
        path = Path(workspace)
        if path.parent != self.state_directory / "workspaces":
            raise ValueError("workspace is outside exclusive node storage")
        parent = os.open("workspaces", _DIR_FLAGS, dir_fd=self._root_fd)
        try:
            with self._db() as db:
                expected_parent = json.loads(db.execute("SELECT value FROM configuration WHERE key='workspace_root'").fetchone()[0])
                row = db.execute("SELECT value FROM configuration WHERE key=?", ("workspace:" + path.name,)).fetchone()
            if [os.fstat(parent).st_dev, os.fstat(parent).st_ino] != expected_parent or row is None:
                raise ValueError("workspace root or reservation pin mismatch")
            fd = os.open(path.name, _DIR_FLAGS, dir_fd=parent)
        finally:
            os.close(parent)
        info = os.fstat(fd)
        if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
                or [info.st_dev, info.st_ino] != json.loads(row[0])):
            os.close(fd)
            raise ValueError("invalid workspace ownership/permissions")
        return fd

    @contextmanager
    def _file_parent(self, root_fd, path, *, create=False):
        fd = os.dup(root_fd)
        try:
            parts = path.split("/")
            for name in parts[:-1]:
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, parts[-1]
        finally:
            os.close(fd)

    def _read_fixed(self, root_fd, entry):
        with self._file_parent(root_fd, entry["path"]) as (parent, name):
            fd = os.open(name, _FILE_FLAGS, dir_fd=parent)
            try:
                before = os.fstat(fd)
                _regular(before)
                if before.st_size != entry["size"] or before.st_size > 8_000_000:
                    raise ValueError("fixed file size mismatch")
                chunks, remaining = [], before.st_size
                while remaining:
                    chunk = os.read(fd, min(remaining, 65536))
                    if not chunk:
                        raise ValueError("fixed file incomplete")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b"".join(chunks)
                if (_stamp(before) != _stamp(os.fstat(fd)) or
                        _stamp(before) != _stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) or
                        hashlib.sha256(data).hexdigest() != entry["sha256"]):
                    raise ValueError("fixed file changed/hash mismatch")
                if self._secret.encode() in data:
                    raise ValueError("fixed file contains node credential material")
                return data
            finally:
                os.close(fd)

    def _inputs(self, request_id, offer):
        attempt = self._attempt(request_id)
        workspace = attempt["workspace"]
        if workspace is None:
            name = "native_" + secrets.token_hex(16)
            parent = os.open("workspaces", _DIR_FLAGS, dir_fd=self._root_fd)
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                os.fsync(parent)
            finally:
                os.close(parent)
            workspace = str(self.state_directory / "workspaces" / name)
            with self._db() as db:
                db.execute("INSERT INTO configuration VALUES(?,?)", ("workspace:" + name, _encoded([info.st_dev, info.st_ino]).decode()))
                db.execute("UPDATE attempts SET workspace=? WHERE request_id=?", (workspace, request_id))
        root = self._workspace_fd(workspace)
        try:
            for entry in offer["input_manifest"]["files"]:
                data = self._call("inputs", offer=offer, path=entry["path"])
                if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError("download differs from fixed input hash/size")
                with self._file_parent(root, entry["path"], create=True) as (parent, name):
                    try:
                        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    except FileExistsError:
                        if self._read_fixed(root, entry) != data:
                            raise ValueError("existing fixed input differs")
                    else:
                        try:
                            view = memoryview(data)
                            while view:
                                written = os.write(fd, view)
                                if not written:
                                    raise OSError("input write made no progress")
                                view = view[written:]
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                        os.fsync(parent)
                self._read_fixed(root, entry)
            tree = full_tree_manifest(workspace)
            os.close(self._workspace_fd(workspace))
            files = offer["input_manifest"]["files"]
            directories = set()
            for item in files:
                parts = item["path"].split("/")
                directories.update("/".join(parts[:i]) for i in range(1, len(parts)))
            expected = sorted([{"path": name, "kind": "directory"} for name in directories] +
                              [{"kind": "file", **entry} for entry in files], key=lambda item: item["path"])
            if not tree["complete"] or tree["errors"] or tree["files"] != files or tree["tree"] != expected:
                raise ValueError("final input tree differs from frozen package")
            os.fsync(root)
        finally:
            os.close(root)
        return workspace

    def _snapshot_terminal(self, request_id, offer):
        attempt = self._attempt(request_id)
        if attempt["tree"] is not None:
            return
        workspace = attempt["workspace"]
        root = self._workspace_fd(workspace)
        try:
            tree = full_tree_manifest(workspace)
            os.close(self._workspace_fd(workspace))
            if self._clean(tree) != tree:
                raise ValueError("terminal tree contains node credential material")
            _tree_payload(tree)
            before = {item["path"]: item for item in offer["input_manifest"]["files"]}
            allowed = set(offer["input_manifest"]["output_paths"])
            uploads = []
            for entry in tree["files"]:
                if entry["path"] in allowed and entry != before.get(entry["path"]):
                    uploads.append((entry, self._read_fixed(root, entry)))
            with self._db() as db:
                for entry, data in uploads:
                    db.execute("INSERT INTO uploads(request_id,path,metadata,bytes) VALUES(?,?,?,?)",
                               (request_id, entry["path"], _encoded(entry).decode(), data))
                db.execute("UPDATE attempts SET tree=? WHERE request_id=?", (_encoded(tree).decode(), request_id))
        finally:
            os.close(root)

    def _native_fact(self, receipt, max_output_bytes):
        """Local native bounds are independent of the smaller N1 wire limit.

        Preserve finite original fields, including fields/types N1 may reject.
        Output is bounded by the original native byte cap; metadata by 1 MB.
        JSON escaping has finite overhead, and never truncates native evidence.
        """
        if isinstance(receipt, Receipt):
            raw = {field.name: getattr(receipt, field.name) for field in fields(Receipt)}
        elif isinstance(receipt, dict):
            raw = dict(receipt)
        else:
            raise ValueError("native result is not a Receipt fact")
        from .node_claims import _sync_json
        _sync_json(raw)
        output = raw.get("output", "")
        output_bytes = output.encode("utf-8") if isinstance(output, str) else _encoded(output)
        if len(output_bytes) > max_output_bytes:
            raise ValueError("native Receipt output exceeds original native byte bound")
        if len(_encoded({key: value for key, value in raw.items() if key != "output"})) > 1_000_000:
            raise ValueError("native Receipt metadata exceeds local retained bound")
        # Node credentials and provider secrets must never reach persisted data.
        return self._clean(redact(raw))

    def _status(self, offer):
        view = self._call("status", self._identity_body(offer))["result"]
        return self._validate_offer(view, original=offer)

    def _finish(self, request_id, offer):
        self._snapshot_terminal(request_id, offer)
        attempt = self._attempt(request_id)
        # A too-large or malformed N1 Receipt remains a known local terminal
        # fact plus full tree. It is never converted to UNKNOWN or fitted by
        # truncation; replay revalidates the same original sanitized fields.
        _receipt_payload(json.loads(attempt["receipt"]))
        if attempt["receipt_body"] is None:
            controller_rejected = False
            try:
                self._sync(request_id, offer)
            except _GatewayError as exc:
                if not exc.authority_lost:
                    raise
                controller_rejected = True
                self._lost(request_id, offer)
            with self._db() as db:
                pending = db.execute("SELECT * FROM uploads WHERE request_id=? AND stored=0 ORDER BY path", (request_id,)).fetchall()
            for row in pending:
                if controller_rejected:
                    break
                entry = json.loads(row["metadata"])
                try:
                    answer = self._call("uploads", offer=offer, path=entry["path"], sha=entry["sha256"], data=row["bytes"])["result"]
                    if _encoded(answer) != _encoded(entry | {"status": "STORED"}):
                        raise ValueError("upload ACK differs from fixed bytes identity")
                    with self._db() as db:
                        db.execute("UPDATE uploads SET stored=1 WHERE request_id=? AND path=?", (request_id, entry["path"]))
                except _GatewayError as exc:
                    if not exc.authority_lost:
                        raise
                    controller_rejected = True
                    self._lost(request_id, offer)
                    break
            if controller_rejected:
                # Readback confirms exactly STORED original bytes, never infers
                # success from a submitted upload or an expired connection.
                view = self._status(offer)
                with self._db() as db:
                    for item in view["uploads"]:
                        if item.get("status") != "STORED":
                            continue
                        local = db.execute("SELECT metadata FROM uploads WHERE request_id=? AND path=?", (request_id, item["path"])).fetchone()
                        if local is None or _encoded(item) != _encoded(json.loads(local[0]) | {"status": "STORED"}):
                            raise ValueError("STORED readback differs from original upload identity")
                        db.execute("UPDATE uploads SET stored=1 WHERE request_id=? AND path=?", (request_id, item["path"]))
            with self._db() as db:
                manifest = [json.loads(row[0]) for row in db.execute("SELECT metadata FROM uploads WHERE request_id=? AND stored=1 ORDER BY path", (request_id,))]
                body = self._identity_body(offer) | {"receipt": json.loads(attempt["receipt"]),
                    "manifest": manifest, "tree": json.loads(attempt["tree"])}
                db.execute("UPDATE attempts SET receipt_body=? WHERE request_id=?", (_encoded(body).decode(), request_id))
        body = json.loads(self._attempt(request_id)["receipt_body"])
        view = self._call("receipt", body)["result"]
        self._validate_offer(view, original=offer)
        canonical_tree = json.loads(_tree_payload(body["tree"])[1])
        canonical_receipt = json.loads(_encoded(redact(_receipt_payload(body["receipt"]))))
        if (_encoded(view.get("receipt")) != _encoded(canonical_receipt)
                or _encoded(view.get("manifest")) != _encoded(body["manifest"])
                or _encoded(view.get("tree")) != _encoded(canonical_tree)):
            raise ValueError("terminal ACK differs from original receipt/tree/manifest")
        self._update(request_id, status="DONE" if view["status"] == "RECEIPTED" else view["status"])
        return {"request_id": request_id, "status": view["status"]}

    def run_once(self):
        """Claim one fixed task or reconcile its original durable identities."""
        with self._exclusive():
            with self._db() as db:
                previous = db.execute("SELECT * FROM attempts ORDER BY rowid DESC LIMIT 1").fetchone()
                if previous is None or previous["status"] == "NO_WORK":
                    request_id = "agent_" + secrets.token_hex(16)
                    db.execute("INSERT INTO attempts(request_id,status) VALUES(?, 'CLAIM_PENDING')", (request_id,))
                else:
                    request_id = previous["request_id"]
            try:
                return self._run_fixed(request_id)
            except Exception as exc:
                self._diagnostic(request_id, f"node transport error: {type(exc).__name__}: {exc}")
                raise RuntimeError(self._clean(f"node transport error [{request_id}]: {type(exc).__name__}: {exc}")[:2000]) from None

    def _run_fixed(self, request_id):
        attempt = self._attempt(request_id)
        if attempt["offer"] is None:
            value = self._call("claim", {"request_id": request_id})["result"]
            if (set(value) != {"mission_id", "node_id", "request_id", "status", "claim"}
                    or value["request_id"] != request_id or value["node_id"] != self.node_id
                    or not _NAMESPACE.fullmatch(str(value["mission_id"]))):
                raise ValueError("claim request/namespace/node identity mismatch")
            with self._db() as db:
                old = db.execute("SELECT value FROM configuration WHERE key='namespace'").fetchone()
                if old is not None and old[0] != value["mission_id"]:
                    raise ValueError("claim namespace changed")
                db.execute("INSERT OR IGNORE INTO configuration VALUES('namespace',?)", (value["mission_id"],))
            if value["status"] == "NO_WORK" and value["claim"] is None:
                self._update(request_id, status="NO_WORK")
                return {"request_id": request_id, "status": "NO_WORK"}
            offer = self._validate_offer(value["claim"])
            if value["status"] != "CLAIMED" or offer["status"] != "CLAIMED" or offer["mission_id"] != value["mission_id"]:
                raise ValueError("claim/offer namespace or status mismatch")
            self._update(request_id, status="INPUTS", offer=_encoded(offer).decode())
        else:
            offer = json.loads(attempt["offer"])
        attempt = self._attempt(request_id)
        if attempt["receipt"] is not None:
            return self._finish(request_id, offer)
        if attempt["status"] in {"IN_FLIGHT", "UNKNOWN"}:
            self._update(request_id, status="UNKNOWN")
            try:
                self._sync(request_id, offer)
            except _GatewayError as exc:
                if not exc.authority_lost:
                    raise
                self._lost(request_id, offer)
            self._status(offer)
            return {"request_id": request_id, "status": "UNKNOWN"}
        if attempt["status"].startswith("NATIVE_"):
            self._snapshot_terminal(request_id, offer)
            raise ValueError("known native terminal fact has a retained local serialization error; no relaunch")
        workspace = self._inputs(request_id, offer)
        self._heartbeat(request_id, offer)
        # Controller UTC fences the lease; only local elapsed time bounds retries.
        initial_heartbeat = time.monotonic()
        native = Request(**(offer["request"] | {"cwd": workspace}))
        if self._secret in _encoded(environment()).decode():
            raise ValueError("node environment contains credential material")
        # The reservation commits before driver.run is even resolved (including
        # a crashing property). Restart cannot infer that spawn did not occur.
        self._update(request_id, status="IN_FLIGHT")
        stop = threading.Event()
        heartbeat_fatal = threading.Event()
        heartbeat_errors = []

        def check_heartbeat():
            if heartbeat_fatal.is_set():
                raise RuntimeError("independent heartbeat fatal error: " + heartbeat_errors[0])

        def native_controls():
            check_heartbeat()
            return self._controls(request_id)

        def beats():
            try:
                last_success = initial_heartbeat
                while not stop.wait(.1):
                    try:
                        self._heartbeat(request_id, offer)
                        last_success = time.monotonic()
                    except Exception as exc:
                        self._diagnostic(request_id, f"heartbeat error: {type(exc).__name__}: {exc}")
                        if (isinstance(exc, ValueError) or isinstance(exc, _GatewayError)
                                and exc.status in {400, 409} and not exc.authority_lost):
                            raise  # Schema/conflict/unknown 409 is not lease expiry.
                        if (isinstance(exc, _GatewayError) and (exc.authority_lost or exc.status == 404)
                                or time.monotonic() - last_success >= _HEARTBEAT_RETRY_SECONDS):
                            self._lost(request_id, offer)
                            return
            except BaseException as exc:
                # Persistence itself may be unavailable. Do not retry the same
                # failing DB operation here or leave a stderr-only thread error.
                heartbeat_errors.append(self._clean(f"{type(exc).__name__}: {exc}")[:2000])
                heartbeat_fatal.set()

        heartbeat = threading.Thread(target=beats, name="node-agent-heartbeat", daemon=True)
        heartbeat.start()
        known_terminal = False
        try:
            os.close(self._workspace_fd(workspace))
            receipt = self.driver.run(native, lambda kind, data: self._emit(request_id, kind, data),
                                      native_controls)
            status = receipt.status if isinstance(receipt, Receipt) else receipt.get("status") if isinstance(receipt, dict) else None
            if isinstance(status, str) and status in {"COMPLETED", "ERROR", "INTERRUPTED", "UNKNOWN"}:
                # Even a subsequent local serialization/bound error retains this
                # observed status; N1's 1 MB rule never erases native completion.
                self._update(request_id, status="NATIVE_" + status)
                known_terminal = True
            fixed = self._native_fact(receipt, native.max_output_bytes)
            if not known_terminal:
                raise ValueError("native result lacks a known terminal status")
            self._update(request_id, status="TERMINAL", receipt=_encoded(fixed).decode())
        except BaseException as exc:
            if not known_terminal:
                self._update(request_id, status="UNKNOWN")
            else:
                self._diagnostic(request_id, f"known native terminal retention error: {type(exc).__name__}: {exc}")
                self._snapshot_terminal(request_id, offer)
            raise
        finally:
            stop.set()
            heartbeat.join(2)
            if heartbeat.is_alive():
                raise RuntimeError("node heartbeat did not stop within bound")
            # Native terminal storage precedes this check. A fatal heartbeat
            # rejects normal completion of run_once, never rewrites that fact.
            check_heartbeat()
        return self._finish(request_id, offer)
