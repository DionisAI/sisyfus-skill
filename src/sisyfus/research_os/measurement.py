"""Independent, bounded arithmetic evaluator used by the offline integration demo.

Candidates are expressions, not executable Python modules. The evaluator accepts
only a small AST and never calls eval/exec or imports candidate code.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
from pathlib import Path


def calculate(node: ast.AST, x: float) -> float:
    if isinstance(node, ast.Expression):
        return calculate(node.body, x)
    if isinstance(node, ast.Name) and node.id == "x":
        return x
    if isinstance(node, ast.Constant) and type(node.value) in (int, float) and abs(node.value) <= 100:
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = calculate(node.operand, x)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        a, b = calculate(node.left, x), calculate(node.right, x)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        return a * b
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        args = [calculate(n, x) for n in node.args]
        if node.func.id == "abs" and len(args) == 1:
            return abs(args[0])
        if node.func.id == "max" and len(args) == 2:
            return max(args)
    raise ValueError("expression contains unsupported syntax")


def measure(expression: str, family: str) -> dict:
    if len(expression) > 200:
        raise ValueError("expression exceeds size limit")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 60:
        raise ValueError("expression exceeds AST limit")
    targets = {"absolute": abs, "square": lambda x: x * x, "nonnegative": lambda x: max(x, 0), "cube": lambda x: x * x * x}
    target = targets[family]
    cases = [-7.0, -2.0, -0.5, 0.0, 0.25, 2.0, 8.0]
    matches = []
    for x in cases:
        try:
            value = calculate(tree, x)
            matches.append(math.isfinite(value) and math.isclose(value, target(x), rel_tol=1e-10, abs_tol=1e-10))
        except (ValueError, OverflowError):
            matches.append(False)
    return {"metrics": {"score": sum(matches) / len(cases), "cases": len(cases)}, "summary": "Independent bounded arithmetic check"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    candidate = json.loads(Path(args.candidate).read_text())
    result = measure(candidate["expression"], args.family)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
