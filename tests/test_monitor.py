from __future__ import annotations

import json
from pathlib import Path

from sisyfus.monitor import MonitorRegistry, route_ops_task
from sisyfus.scaffold import init_project
from sisyfus.verifier import verify_goal


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_csv_numeric_close_passes_with_tolerance(tmp_path: Path) -> None:
    init_project(tmp_path)
    write(tmp_path / "live.csv", "ts,symbol,price,qty\n1,AAPL,100.0000001,5\n2,AAPL,101.0,6\n")
    write(tmp_path / "bt.csv", "ts,symbol,price,qty\n1,AAPL,100.0000002,5\n2,AAPL,101.0,6\n")
    result = MonitorRegistry(tmp_path).run(
        "csv.numeric_close",
        params={"left": "live.csv", "right": "bt.csv", "key": "ts,symbol", "columns": "price,qty", "abs_tol": "1e-6"},
        workdir=tmp_path,
    )
    assert result["status"] == "PASSED"
    assert result["metrics"]["compared_values"] == 4


def test_csv_numeric_close_fails_on_mismatch(tmp_path: Path) -> None:
    init_project(tmp_path)
    write(tmp_path / "live.csv", "ts,symbol,price\n1,AAPL,100\n")
    write(tmp_path / "bt.csv", "ts,symbol,price\n1,AAPL,101\n")
    result = MonitorRegistry(tmp_path).run(
        "csv.numeric_close",
        params={"left": "live.csv", "right": "bt.csv", "key": "ts,symbol", "columns": "price", "abs_tol": "0.01"},
        workdir=tmp_path,
    )
    assert result["status"] == "FAILED"
    assert result["mismatches"][0]["type"] == "numeric_mismatch"


def test_verifier_can_pass_using_monitor_without_commands(tmp_path: Path) -> None:
    init_project(tmp_path)
    write(tmp_path / "a.csv", "id,v\n1,2\n")
    write(tmp_path / "b.csv", "id,v\n1,2\n")
    goal = {
        "id": "monitor-only",
        "objective": "verify CSVs match",
        "done_when": {"commands": []},
        "monitors": [{"id": "csv.numeric_close", "params": {"left": "a.csv", "right": "b.csv", "key": "id", "columns": "v"}}],
        "constraints": {"require_small_diff": False},
    }
    result = verify_goal(goal, workdir=tmp_path, root=tmp_path)
    assert result["status"] == "PASSED"
    assert result["monitors"][0]["monitor_id"] == "csv.numeric_close"


def test_ops_router_uses_existing_monitor_for_live_backtest(tmp_path: Path) -> None:
    init_project(tmp_path)
    write(tmp_path / "live.csv", "ts,price\n1,10\n")
    write(tmp_path / "bt.csv", "ts,price\n1,10\n")
    result = route_ops_task(
        tmp_path,
        task="实盘和回测的数据对比，检测 price 是否一致",
        params={"left": "live.csv", "right": "bt.csv", "key": "ts", "columns": "price"},
        workdir=tmp_path,
    )
    assert result["status"] == "PASSED"
    assert result["routing"]["selected_monitor"] == "csv.numeric_close"


def test_custom_command_monitor_registration(tmp_path: Path) -> None:
    init_project(tmp_path)
    registry = MonitorRegistry(tmp_path)
    registry.add_custom(
        "custom.ok",
        description="always returns pass json",
        command='printf \'{"status":"PASSED","summary":"ok"}\n\'',
        tags=["ok"],
    )
    result = registry.run("custom.ok", workdir=tmp_path)
    assert result["status"] == "PASSED"
    registry_json = json.loads((tmp_path / ".sisyfus" / "monitors" / "registry.json").read_text())
    assert registry_json["monitors"][0]["usage_count"] == 1
