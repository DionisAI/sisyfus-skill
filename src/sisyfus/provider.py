from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import ensure_layout, find_project_root
from .utils import append_jsonl, read_jsonl, utc_now, write_json


COST_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "anthropic-fable-5": (10.0, 50.0),
    "gpt-5.5-xhigh": (8.0, 40.0),
    "gpt-5.6-xhigh": (10.0, 50.0),
    "claude-sonnet-4.6": (3.0, 15.0),
    "gpt-5.4-mini": (1.0, 4.0),
    "deepseek-v4": (1.0, 3.0),
    "none": (0.0, 0.0),
}


def provider_dir(root: str | Path | None = None) -> Path:
    return ensure_layout(find_project_root(root)) / "provider"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = COST_PER_MILLION.get(str(model), (0.0, 0.0))
    return round((input_tokens / 1_000_000) * inp + (output_tokens / 1_000_000) * out, 6)


def provider_record_from_agent_result(root: str | Path | None, *, run_dir: str | Path, result: dict[str, Any]) -> dict[str, Any]:
    root_path = find_project_root(root)
    run_path = Path(run_dir).resolve()
    meta = result.get("metadata") or {}
    route = meta.get("model_route") or {}
    model = str(route.get("model") or "none")
    in_tok = int(meta.get("approx_prompt_tokens") or max(0, int(result.get("prompt_chars") or 0) // 4))
    out_tok = int(meta.get("approx_output_tokens") or max(0, int(result.get("output_chars") or 0) // 4))
    provider_payload = meta.get("provider") if isinstance(meta.get("provider"), dict) else {}
    actual_model = str(provider_payload.get("actual_model") or meta.get("actual_model") or model)
    item = {
        "schema_version": "sisyfus.provider_usage.v0.6",
        "created_at": utc_now(),
        "run_id": run_path.name,
        "role": result.get("role"),
        "round": result.get("round_index"),
        "adapter": result.get("adapter"),
        "requested_model": model,
        "actual_model": actual_model,
        "fallback_model": provider_payload.get("fallback_model") if provider_payload else None,
        "safeguard_fallback": bool(provider_payload.get("safeguard_fallback", False)) if provider_payload else False,
        "provider_flags": provider_payload.get("provider_flags", []) if provider_payload else [],
        "model_profile": route.get("profile_id"),
        "effort": route.get("reasoning"),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "estimated_usd": estimate_cost(actual_model, in_tok, out_tok),
        "prompt_path": result.get("prompt_path"),
        "stdout_path": result.get("stdout_path"),
        "stderr_path": result.get("stderr_path"),
        "exit_code": result.get("exit_code"),
    }
    append_jsonl(provider_dir(root_path) / "usage.jsonl", item)
    append_jsonl(run_path / "provider_usage.jsonl", item)
    return item


def summarize_provider_usage(root: str | Path | None = None, *, limit: int = 100000) -> dict[str, Any]:
    items = read_jsonl(provider_dir(root) / "usage.jsonl")[-limit:]
    by_model: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    total_input = 0
    total_output = 0
    fallback_count = 0
    for item in items:
        m = str(item.get("actual_model") or item.get("requested_model") or "unknown")
        rec = by_model.setdefault(m, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_usd": 0.0})
        rec["calls"] += 1
        rec["input_tokens"] += int(item.get("input_tokens", 0) or 0)
        rec["output_tokens"] += int(item.get("output_tokens", 0) or 0)
        rec["estimated_usd"] = round(float(rec["estimated_usd"]) + float(item.get("estimated_usd", 0) or 0), 6)
        total_cost += float(item.get("estimated_usd", 0) or 0)
        total_input += int(item.get("input_tokens", 0) or 0)
        total_output += int(item.get("output_tokens", 0) or 0)
        if item.get("safeguard_fallback") or item.get("fallback_model"):
            fallback_count += 1
    return {
        "schema_version": "sisyfus.provider_summary.v0.6",
        "call_count": len(items),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "estimated_usd": round(total_cost, 6),
        "fallback_count": fallback_count,
        "by_model": by_model,
    }
