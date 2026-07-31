from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sisyfus.cli import main
from sisyfus.research_v2 import live
from sisyfus.research_v2.engine import ResearchEngine


def spec() -> dict:
    return {
        "id": "live-observatory",
        "topic": "Live observatory",
        "claims": [{"id": "a", "statement": "Claim A holds", "label": "A"}],
        "action_space": ["experiment"],
        "verification_contracts": [
            {"id": "va", "target_claim_id": "a", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
        ],
    }


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format, *args):
        pass


def _listening_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, int(server.server_address[1])


def test_derived_port_stable_and_in_range(tmp_path: Path) -> None:
    port = live.derived_port(tmp_path)
    assert port == live.derived_port(tmp_path)
    assert 8700 <= port < 8900


def test_render_writes_stable_entry_page(tmp_path: Path) -> None:
    engine = ResearchEngine.create(tmp_path, spec())
    entry = live.observatory_entry_path(engine.workspace.root)
    assert entry.exists()
    text = entry.read_text(encoding="utf-8")
    assert f"http://127.0.0.1:{live.derived_port(engine.workspace.root)}" in text
    assert "Live observatory" in text
    assert "location.replace" in text
    # The run report itself must stay free of the file:// bootstrap.
    assert "location.replace" not in engine.workspace.report_path.read_text(encoding="utf-8")


def test_entry_page_embeds_recorded_live_port(tmp_path: Path) -> None:
    engine = ResearchEngine.create(tmp_path, spec())
    live.write_live_state(engine.workspace.root, host="127.0.0.1", port=61234, research_id=engine.workspace.research_id)
    engine.sync(render=True)
    assert "http://127.0.0.1:61234" in live.observatory_entry_path(engine.workspace.root).read_text(encoding="utf-8")


def test_live_url_requires_answering_socket(tmp_path: Path) -> None:
    (tmp_path / ".sisyfus").mkdir()
    assert live.live_observatory_url(tmp_path) is None
    server, port = _listening_server()
    try:
        live.write_live_state(tmp_path, host="127.0.0.1", port=port, research_id="research-x")
        assert live.live_observatory_url(tmp_path) == f"http://127.0.0.1:{port}/index.html"
    finally:
        server.shutdown()
        server.server_close()
    assert live.live_observatory_url(tmp_path) is None  # stale state file, dead port


def test_ensure_spawns_detached_daemon_when_dead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SISYFUS_AUTO_SERVE", "1")
    calls: list[list[str]] = []
    monkeypatch.setattr(live.subprocess, "Popen", lambda argv, **kwargs: calls.append(list(argv)))
    (tmp_path / ".sisyfus").mkdir()
    url = live.ensure_observatory(tmp_path, "research-y", spawn_timeout=0.1)
    assert url is None  # fake spawner never comes alive
    assert len(calls) == 1
    assert calls[0][-4:] == ["serve", "research-y", "--root", str(tmp_path.resolve())]


def test_ensure_disabled_by_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SISYFUS_AUTO_SERVE", "0")
    monkeypatch.setattr(live.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    (tmp_path / ".sisyfus").mkdir()
    assert live.ensure_observatory(tmp_path, "research-z", spawn_timeout=0.1) is None


def test_ensure_returns_url_of_alive_daemon_without_respawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SISYFUS_AUTO_SERVE", "1")
    monkeypatch.setattr(live.subprocess, "Popen", lambda *a, **k: pytest.fail("must not respawn an alive daemon"))
    server, port = _listening_server()
    try:
        (tmp_path / ".sisyfus").mkdir()
        live.write_live_state(tmp_path, host="127.0.0.1", port=port, research_id="research-a")
        assert live.ensure_observatory(tmp_path, "research-a") == f"http://127.0.0.1:{port}/index.html"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_summary_reports_observatory_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ResearchEngine.create(tmp_path, spec())
    assert main(["research", "status", "latest", "--root", str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["observatory_entry"] == str(live.observatory_entry_path(tmp_path.resolve()))
    assert "observatory_url" not in summary  # no daemon alive, so no live claim


def test_cli_summary_reports_live_url_when_daemon_alive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ResearchEngine.create(tmp_path, spec())
    server, port = _listening_server()
    try:
        live.write_live_state(tmp_path.resolve(), host="127.0.0.1", port=port, research_id="research-x")
        assert main(["research", "status", "latest", "--root", str(tmp_path)]) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["observatory_url"] == f"http://127.0.0.1:{port}/index.html"
    finally:
        server.shutdown()
        server.server_close()


def test_resolve_serve_port_is_idempotent_for_same_run(tmp_path: Path) -> None:
    (tmp_path / ".sisyfus").mkdir()
    server, port = _listening_server()
    try:
        live.write_live_state(tmp_path, host="127.0.0.1", port=port, research_id="research-b")
        with pytest.raises(live.AlreadyServing) as exc:
            live.resolve_serve_port(tmp_path, "research-b", None)
        assert exc.value.url == f"http://127.0.0.1:{port}/index.html"
        # An explicit port always wins, even over an alive daemon.
        assert live.resolve_serve_port(tmp_path, "research-b", 9999) == 9999
    finally:
        server.shutdown()
        server.server_close()


def test_clear_live_state_respects_newer_owner(tmp_path: Path) -> None:
    (tmp_path / ".sisyfus").mkdir()
    live.write_live_state(tmp_path, host="127.0.0.1", port=1, research_id="research-c")
    live.clear_live_state(tmp_path, pid=live.read_live_state(tmp_path)["pid"] + 1)
    assert live.read_live_state(tmp_path) is not None  # someone else's file survives
    live.clear_live_state(tmp_path)
    assert live.read_live_state(tmp_path) is None


def test_state_from_copied_project_dir_is_ignored(tmp_path: Path) -> None:
    original, copy = tmp_path / "orig", tmp_path / "copy"
    (original / ".sisyfus").mkdir(parents=True)
    server, port = _listening_server()
    try:
        live.write_live_state(original, host="127.0.0.1", port=port, research_id="research-r")
        assert live.live_observatory_url(original) is not None
        # Simulate copying the whole project directory elsewhere.
        (copy / ".sisyfus").mkdir(parents=True)
        state_text = live.observatory_state_path(original).read_text(encoding="utf-8")
        live.observatory_state_path(copy).write_text(state_text, encoding="utf-8")
        assert live.read_live_state(copy) is None
        assert live.live_observatory_url(copy) is None  # even though the old daemon answers
    finally:
        server.shutdown()
        server.server_close()


class _FakeServer:
    server_address = ("127.0.0.1", 54321)

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        pass


def test_serve_defers_when_concurrent_spawn_wins_the_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = ResearchEngine.create(tmp_path, spec())
    root, rid = engine.workspace.root, engine.workspace.research_id
    server, port = _listening_server()

    def racing_bind(self, **kwargs):  # rival registers between our resolve and bind
        live.write_live_state(root, host="127.0.0.1", port=port, research_id=rid)
        raise OSError(48, "address already in use")

    monkeypatch.setattr(ResearchEngine, "serve_report", racing_bind)
    try:
        assert main(["research", "serve", "latest", "--root", str(tmp_path)]) == 0
        assert f"already live at http://127.0.0.1:{port}/index.html" in capsys.readouterr().out
    finally:
        server.shutdown()
        server.server_close()


def test_serve_falls_back_to_ephemeral_port_for_foreign_occupier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = ResearchEngine.create(tmp_path, spec())
    root = engine.workspace.root
    ports: list[object] = []

    def flaky_bind(self, *, host, port, open_browser, verbose):
        ports.append(port)
        if len(ports) == 1:
            raise OSError(48, "address already in use")
        return _FakeServer(), "http://127.0.0.1:54321/index.html"

    monkeypatch.setattr(ResearchEngine, "serve_report", flaky_bind)
    assert main(["research", "serve", "latest", "--root", str(tmp_path)]) == 0
    assert ports == [live.derived_port(root), 0]
    assert "listening on http://127.0.0.1:54321" in capsys.readouterr().out
    assert live.read_live_state(root) is None  # cleared on shutdown by its owner
