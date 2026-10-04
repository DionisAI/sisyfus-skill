"""Self-contained bounded evaluator and deliberately weak non-LLM smoke worker.

The tiny fixtures test hidden counterexamples, not actual research intelligence.
No eval/exec, candidate imports, file paths or arbitrary commands are accepted.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
from pathlib import Path


def calculate(node: ast.AST, values: dict) -> float:
    if isinstance(node, ast.Expression):
        return calculate(node.body, values)
    if isinstance(node, ast.Name) and node.id in values:
        return float(values[node.id])
    if isinstance(node, ast.Constant) and type(node.value) in (int, float) and abs(node.value) <= 10000:
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        x = calculate(node.operand, values)
        return -x if isinstance(node.op, ast.USub) else x
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        a, b = calculate(node.left, values), calculate(node.right, values)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        return a / b
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        args = [calculate(n, values) for n in node.args]
        if node.func.id == "abs" and len(args) == 1:
            return abs(args[0])
        if node.func.id in {"min", "max"} and len(args) == 2:
            return (min if node.func.id == "min" else max)(args)
    raise ValueError("unsupported candidate syntax")


def measure(candidate: dict, cases: list[dict]) -> dict:
    if not cases:
        raise ValueError("empty reference cases")
    matches = []
    try:
        expression = candidate["expression"]
        if not isinstance(expression, str) or len(expression) > 512:
            raise ValueError("invalid expression")
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("expression too complex")
        for row in cases:
            value = calculate(tree, row["inputs"])
            matches.append(math.isfinite(value) and math.isclose(value, row["expected"], rel_tol=1e-9, abs_tol=1e-9))
    except (ValueError, KeyError, TypeError, ArithmeticError, SyntaxError, RecursionError):
        return {"metrics": {"score": 0.0, "cases": len(cases)}, "summary": "Invalid candidate or undefined arithmetic"}
    return {"metrics": {"score": sum(matches) / len(matches), "cases": len(matches)},
            "summary": "Frozen reference comparison; no candidate-supplied verdict"}


def create_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=False)
    root.joinpath("evaluator.py").write_text(Path(__file__).read_text())
    tasks = []
    for name, expected in (("absolute", 7), ("square", 49), ("nonnegative", 0)):
        case_path = root / (name + ".json")
        case_path.write_text(json.dumps({
            "development": [{"inputs": {"x": 0}, "expected": 0}, {"inputs": {"x": 1}, "expected": 1}],
            "holdout": [{"inputs": {"x": -7}, "expected": expected}],
        }))
        tasks.append({"id": name, "family": name, "prompt": f"Find a numeric expression in x computing {name}. Return artifact {{\"expression\": \"...\"}}. Allowed: numbers, x, +, -, *, /, abs, min, max.",
                      "evaluator": "evaluator.py", "cases": case_path.name, "threshold": 1})
    path = root / "suite.json"
    path.write_text(json.dumps({"schema": "sisyfus.benchmark_suite.v1", "tasks": tasks}))
    return path


class FixtureProvider:
    """Always proposes x. Synthetic usage tests accounting, not model capability."""
    model = "fixture-not-an-llm"
    live = False

    def __init__(self):
        self.requests = 0

    def describe(self) -> dict:
        return {"provider": "scripted-fixture", "requested_model": self.model,
                "live_transport": False, "usage_is_synthetic": True}

    def count_input(self, messages: list[dict], timeout: float) -> int:
        return len(json.dumps(messages).encode())

    def generate(self, messages: list[dict], max_output_tokens: int, timeout: float):
        from .benchmark_provider import Reply
        self.requests += 1
        text = json.dumps({"candidates": [{"artifact": {"expression": "x"}, "title": "Unvalidated candidate"}]})
        return Reply(text, "fixture-" + str(self.requests), self.model,
                     self.count_input(messages, timeout), 1)


def main() -> None:
    p = argparse.ArgumentParser()
    for name in ("cases", "candidate", "output"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--split", choices=("development", "holdout"), required=True)
    args = p.parse_args()
    result = measure(json.loads(Path(args.candidate).read_text()), json.loads(Path(args.cases).read_text())[args.split])
    Path(args.output).write_text(json.dumps(result, allow_nan=False))
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
