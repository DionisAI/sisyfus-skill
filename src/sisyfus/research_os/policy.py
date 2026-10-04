from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .models import Candidate, FEATURES, Judgment, digest, number


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, x))))


@dataclass(frozen=True)
class SchedulingPolicy:
    """A small inspectable ranker, not a proof of scientific or business value."""

    name: str = "fixed-value"
    weights: tuple[float, ...] = (1.0, 1.0, 0.35, 0.25, -0.5, -0.75)
    bias: float = 0.0
    learned: bool = False
    cost_weight: float = 0.2
    judgment_weight: float = 0.0
    selection: str = "value"

    def __post_init__(self) -> None:
        if len(self.weights) != len(FEATURES):
            raise ValueError("policy feature schema mismatch")
        for x in (*self.weights, self.bias):
            number(x, minimum=-100, maximum=100)
        number(self.cost_weight, maximum=100)
        number(self.judgment_weight, maximum=10)
        if self.selection not in {"value", "fifo"}:
            raise ValueError("unknown selection rule")

    @property
    def hash(self) -> str:
        return digest(asdict(self))

    @classmethod
    def load(cls, value: dict[str, Any]) -> "SchedulingPolicy":
        return cls(**{**value, "weights": tuple(value["weights"])})

    def predict(self, features: tuple[float, ...]) -> float:
        if len(features) != len(self.weights):
            raise ValueError("feature schema mismatch")
        value = self.bias + sum(w * x for w, x in zip(self.weights, features))
        return sigmoid(value) if self.learned else value

    def rank(self, candidates: Iterable[Candidate], judgments: dict[str, Judgment] | None = None) -> list[Candidate]:
        candidates = list(candidates)
        if self.selection == "fifo":
            return sorted(candidates, key=lambda c: c.id)
        judgments = judgments or {}

        def score(c: Candidate) -> float:
            j = judgments.get(c.id, Judgment())
            return self.predict(c.features) - self.cost_weight * c.cost + self.judgment_weight * (j.actionable - j.duplicate)

        return sorted(candidates, key=lambda c: (-score(c), c.id))


def fit_policy(rows: list[dict[str, Any]], *, epochs: int = 150, learning_rate: float = 0.15) -> SchedulingPolicy:
    """Fit a log-loss outcome model on executed training rows only.

    Labels mean PASS under the recorded contract, not 'important research'.
    Unchosen actions have no labels. Split enforcement belongs to PolicyLab.
    """
    if len(rows) < 2 or type(epochs) is not int or not 1 <= epochs <= 10000:
        raise ValueError("need at least two observations and a bounded epoch count")
    number(learning_rate, minimum=1e-6, maximum=1)
    data = []
    for row in rows:
        candidate = Candidate.load(row["candidate"])
        label = number(row["label"], maximum=1)
        if label not in (0, 1):
            raise ValueError("binary labels required")
        data.append((candidate.features, label))
    weights = [0.0] * len(FEATURES)
    bias = 0.0
    for _ in range(epochs):
        grad = [0.0] * len(weights)
        gb = 0.0
        for features, label in data:
            error = sigmoid(bias + sum(w * x for w, x in zip(weights, features))) - label
            gb += error
            for i, x in enumerate(features):
                grad[i] += error * x
        bias -= learning_rate * gb / len(data)
        weights = [max(-30, min(30, w - learning_rate * (g / len(data) + 0.001 * w))) for w, g in zip(weights, grad)]
    return SchedulingPolicy(name="learned-pass-v1", weights=tuple(weights), bias=bias, learned=True)
