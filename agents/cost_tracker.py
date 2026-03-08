from __future__ import annotations

from dataclasses import dataclass, field

# claude-3-5-sonnet: $3/1M input, $15/1M output
# gemini-1.5-flash:  $0.075/1M input, $0.30/1M output
_PRICING: dict[str, tuple[float, float]] = {
    "claude": (3.0, 15.0),
    "gemini-flash": (0.075, 0.30),
}


@dataclass
class CostTracker:
    budget: float = 3.97
    used: float = field(default=0.0)
    total_tokens: int = field(default=0)

    def add(self, input_tokens: int, output_tokens: int, model: str = "claude") -> float:
        rate_in, rate_out = _PRICING.get(model, (0.0, 0.0))
        cost = input_tokens * rate_in / 1_000_000 + output_tokens * rate_out / 1_000_000
        self.used += cost
        self.total_tokens += input_tokens + output_tokens
        return cost

    @property
    def remaining(self) -> float:
        return self.budget - self.used

    def context_pct(self, window: int = 200_000) -> int:
        return min(100, int(self.total_tokens / window * 100))

    def metrics_str(self) -> str:
        return f"[Metrics: ${self.used:.4f}/${self.budget:.2f} | Context: {self.context_pct()}%]"


# CLI 模式全局实例
_global = CostTracker()


def get() -> CostTracker:
    return _global
