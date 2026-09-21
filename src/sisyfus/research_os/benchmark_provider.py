"""Optional text-only provider for budget-matched benchmarks.

No retries, remote tools, implicit model fallback, or network calls on import.
Rate cards are operator supplied estimates, not invoices or current price claims.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from .models import number


def count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 100_000_000:
        raise ValueError("invalid token count")
    return value


@dataclass(frozen=True)
class Reply:
    text: str
    response_id: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    status: str = "completed"
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        for n in (self.input_tokens, self.output_tokens, self.cached_tokens, self.reasoning_tokens):
            count(n)
        if self.cached_tokens > self.input_tokens or self.reasoning_tokens > self.output_tokens:
            raise ValueError("invalid token details")
        if not isinstance(self.response_id, str) or not self.response_id or not isinstance(self.actual_model, str) or not self.actual_model or not isinstance(self.text, str):
            raise ValueError("missing provider receipt")
        if len(self.text.encode()) > 1_000_000:
            raise ValueError("provider response too large")


class Provider(Protocol):
    model: str
    live: bool

    def describe(self) -> dict[str, Any]: ...
    def count_input(self, messages: list[dict], timeout: float) -> int: ...
    def generate(self, messages: list[dict], max_output_tokens: int, timeout: float) -> Reply: ...


class OpenAIProvider:
    """A real SDK adapter. Supplying a test client never counts as live evidence."""
    def __init__(self, model: str, *, effort: str = "medium", client: Any = None):
        if not model or not isinstance(model, str):
            raise ValueError("an explicit API model ID is required")
        if effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("unsupported reasoning effort")
        self.model, self.effort = model, effort
        self.live = client is None
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is not configured; no provider request was made")
            from openai import OpenAI
            client = OpenAI(max_retries=0)
        self.client = client

    def describe(self) -> dict[str, Any]:
        return {"provider": "openai-responses", "requested_model": self.model,
                "reasoning_effort": self.effort, "live_transport": self.live,
                "tools": [], "max_retries": 0, "store": False}

    def count_input(self, messages: list[dict], timeout: float) -> int:
        result = self.client.with_options(timeout=timeout, max_retries=0).responses.input_tokens.count(
            model=self.model, input=messages)
        return count(result.input_tokens)

    def generate(self, messages: list[dict], max_output_tokens: int, timeout: float) -> Reply:
        response = self.client.with_options(timeout=timeout, max_retries=0).responses.create(
            model=self.model, input=messages, reasoning={"effort": self.effort},
            max_output_tokens=max_output_tokens, store=False)
        usage = response.usage
        if usage is None:
            raise ValueError("response usage missing; spending is unresolved")
        # output_tokens already includes reasoning: never add it a second time.
        return Reply(response.output_text, response.id, response.model,
                     usage.input_tokens, usage.output_tokens, response.status,
                     getattr(usage.input_tokens_details, "cached_tokens", 0),
                     getattr(usage.output_tokens_details, "reasoning_tokens", 0))


@dataclass(frozen=True)
class Limits:
    max_calls: int = 3
    max_evaluations: int = 6
    max_output_tokens: int = 12_000
    max_output_per_call: int = 4_000
    max_seconds: float = 300.0
    max_usd: float = 1.0

    def __post_init__(self) -> None:
        for value in (self.max_calls, self.max_evaluations, self.max_output_tokens, self.max_output_per_call):
            if type(value) is not int or not 1 <= value <= 1_000_000:
                raise ValueError("limits must be positive bounded integers")
        if self.max_calls > 100 or self.max_evaluations > 100:
            raise ValueError("pilot is limited to 100 calls and evaluations per arm/task")
        number(self.max_seconds, minimum=1, maximum=86400)
        number(self.max_usd, minimum=0.000001, maximum=1000)


@dataclass(frozen=True)
class Rates:
    input_per_million: float
    output_per_million: float

    def __post_init__(self) -> None:
        number(self.input_per_million, minimum=0.000001, maximum=10000)
        number(self.output_per_million, minimum=0.000001, maximum=10000)

    def estimate(self, inputs: int, outputs: int) -> float:
        return (count(inputs) * self.input_per_million + count(outputs) * self.output_per_million) / 1_000_000


class Meter:
    """Reserve counted input + maximum output; unknown requests keep reservations."""
    def __init__(self, limits: Limits, rates: Rates):
        self.limits, self.rates = limits, rates
        self.calls = self.inputs = self.outputs = 0
        self.spent = self.reserved = 0.0
        self.pending: dict | None = None
        self.violated = False

    def reserve(self, input_tokens: int) -> int:
        if self.pending:
            raise RuntimeError("unresolved provider request; reconciliation required")
        cap = min(self.limits.max_output_per_call, self.limits.max_output_tokens - self.outputs)
        if self.calls >= self.limits.max_calls or cap < 1:
            return 0
        cost = self.rates.estimate(input_tokens, cap)
        if self.spent + cost > self.limits.max_usd + 1e-12:
            return 0
        self.calls += 1
        self.reserved = cost
        self.pending = {"input_tokens": input_tokens, "max_output_tokens": cap}
        return cap

    def release(self) -> None:
        """Release a reservation only when no provider request was dispatched."""
        if self.pending is None:
            raise RuntimeError("no reserved provider request")
        if self.calls < 1:
            raise RuntimeError("provider call accounting underflow")
        self.calls -= 1
        self.pending, self.reserved = None, 0.0

    def settle(self, reply: Reply) -> None:
        if self.pending is None:
            raise RuntimeError("no reserved provider request")
        expected = self.pending
        actual = self.rates.estimate(reply.input_tokens, reply.output_tokens)
        self.violated |= reply.input_tokens > expected["input_tokens"] or reply.output_tokens > expected["max_output_tokens"]
        self.inputs += reply.input_tokens
        self.outputs += reply.output_tokens
        self.spent += actual
        self.violated |= self.spent > self.limits.max_usd + 1e-12
        self.pending, self.reserved = None, 0.0

    def public(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.inputs, "output_tokens": self.outputs,
                "token_priced_usd": self.spent, "reserved_usd": self.reserved,
                "unresolved": self.pending is not None, "budget_violation": self.violated,
                "pricing_basis": "operator_rates_uncached_input_conservative_not_invoice"}
