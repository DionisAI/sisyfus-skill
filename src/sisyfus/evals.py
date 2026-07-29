from __future__ import annotations

import tempfile
import shutil
from pathlib import Path
from typing import Any

from .goal import write_goal_template
from .monitor import MonitorRegistry, route_ops_task
from .orchestrator import SisyfusRunner
from .scaffold import init_project
from .utils import utc_now, write_json
from .verifier import verify_goal


def run_builtin_evals(root: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    eval_root = Path(tempfile.mkdtemp(prefix="sisyfus-eval-"))
    try:
        init_project(eval_root)
        pass_goal = eval_root / ".sisyfus" / "goals" / "eval-pass.json"
        fail_goal = eval_root / ".sisyfus" / "goals" / "eval-fail.json"
        write_goal_template(pass_goal, goal_id="eval-pass", objective="Pass a deterministic command", commands=["printf ok"], max_rounds=1)
        write_goal_template(fail_goal, goal_id="eval-fail", objective="Fail a deterministic command", commands=["false"], max_rounds=1)
        runner = SisyfusRunner(eval_root)
        r1 = runner.run(pass_goal, adapter_name="mock", apply_distill=True)
        r2 = runner.run(fail_goal, adapter_name="mock", apply_distill=True)
        results.append({"name": "passing_goal_reaches_passed", "passed": r1["status"] == "PASSED", "status": r1["status"]})
        results.append({"name": "failing_goal_does_not_pass", "passed": r2["status"] in {"FAILED", "NEEDS_HUMAN"}, "status": r2["status"]})
        failures = (eval_root / ".sisyfus" / "memory" / "failures.jsonl").read_text(encoding="utf-8")
        results.append({"name": "failed_run_distills_failure", "passed": "eval-fail" in failures, "status": "checked"})

        (eval_root / "live.csv").write_text("ts,symbol,price\n1,AAPL,100.0000001\n", encoding="utf-8")
        (eval_root / "backtest.csv").write_text("ts,symbol,price\n1,AAPL,100.0000002\n", encoding="utf-8")
        mon = MonitorRegistry(eval_root).run(
            "csv.numeric_close",
            params={"left": "live.csv", "right": "backtest.csv", "key": "ts,symbol", "columns": "price", "abs_tol": "1e-6"},
            workdir=eval_root,
        )
        results.append({"name": "csv_numeric_monitor_passes", "passed": mon["status"] == "PASSED", "status": mon["status"]})

        monitor_goal = {
            "id": "eval-monitor-goal",
            "objective": "Pass using a deterministic monitor only",
            "done_when": {"commands": []},
            "monitors": [
                {"id": "csv.numeric_close", "params": {"left": "live.csv", "right": "backtest.csv", "key": "ts,symbol", "columns": "price", "abs_tol": "1e-6"}}
            ],
            "constraints": {"require_small_diff": False},
        }
        ver = verify_goal(monitor_goal, workdir=eval_root, root=eval_root)
        results.append({"name": "verifier_accepts_monitor_only_goal", "passed": ver["status"] == "PASSED", "status": ver["status"]})

        routed = route_ops_task(
            eval_root,
            task="实盘和回测的数据对比，检测 price 是否一致",
            params={"left": "live.csv", "right": "backtest.csv", "key": "ts,symbol", "columns": "price", "abs_tol": "1e-6"},
            workdir=eval_root,
        )
        results.append({"name": "ops_router_reuses_existing_monitor", "passed": routed["status"] == "PASSED" and routed.get("routing", {}).get("selected_monitor") == "csv.numeric_close", "status": routed["status"]})
    finally:
        shutil.rmtree(eval_root, ignore_errors=True)

    sf = root / ".sisyfus"
    out_dir = sf / "evals" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "sisyfus.eval.v0.2",
        "created_at": utc_now(),
        "passed": all(r["passed"] for r in results),
        "results": results,
    }
    out = out_dir / (utc_now().replace(":", "").replace("-", "") + ".json")
    write_json(out, summary)
    summary["path"] = str(out)
    return summary
