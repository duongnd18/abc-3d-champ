"""Per-prompt budget ledger, counted the way the runtime counts it (docs/07 §3, pricing.json).

A call costs input_tokens * input_weight + output_tokens * output_weight; cached input tokens count at the full
input rate, and every dispatched request is one call, including provider rejections. Before a request is sent,
the ledger holds one call and its worst-case credits so that parallel calls cannot overrun the cap together.
Decisions depend only on recorded usage, so a replay makes the same decisions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PRICING: dict[str, Any] = json.loads(Path(__file__).with_name("pricing.json").read_text())


class BudgetExceeded(RuntimeError):
    """Raised before dispatch when a call would not fit the remaining calls or credits."""


def credits(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICING["models"][model]
    long = input_tokens > PRICING["long_context_above_input_tokens"]
    w_in = float(rates["long_input_credits_per_token" if long else "input_credits_per_token"])
    w_out = float(rates["long_output_credits_per_token" if long else "output_credits_per_token"])
    return input_tokens * w_in + output_tokens * w_out


@dataclass
class Ledger:
    max_calls: int
    max_credits: float
    reserve_calls: int = 1
    calls: int = 0
    spent: float = 0.0
    held: float = 0.0
    log: list[dict[str, Any]] = field(default_factory=list)

    def can(self, n_calls: int, est_credits: float, *, use_reserve: bool = False) -> bool:
        free = self.max_calls - self.calls - (0 if use_reserve else self.reserve_calls)
        return free >= n_calls and self.spent + self.held + est_credits <= self.max_credits

    def hold(self, stage: str, model: str, est_input: int, max_output: int, *, use_reserve: bool = False) -> float:
        """Reserve one call and its worst-case credits; call before dispatch, in a fixed order."""
        est = credits(model, est_input, max_output)
        if not self.can(1, est, use_reserve=use_reserve):
            left = self.max_credits - self.spent - self.held
            raise BudgetExceeded(
                f"{stage}: {self.max_calls - self.calls} calls, {left:,.0f} credits left; needs ~{est:,.0f}"
            )
        self.calls += 1
        self.held += est
        return est

    def settle(self, held: float, entry: dict[str, Any]) -> None:
        """Release the hold and charge the call's verified credits (or the hold, when usage is unknown)."""
        self.held -= held
        self.spent += float(entry.get("credits", 0.0))
        self.log.append(entry)

    def summary(self) -> dict[str, Any]:
        by_stage: dict[str, dict[str, float]] = {}
        for entry in self.log:
            stage = by_stage.setdefault(entry["stage"], {"calls": 0, "credits": 0.0})
            stage["calls"] += 1
            stage["credits"] = round(stage["credits"] + float(entry.get("credits", 0.0)))
        return {
            "calls": self.calls,
            "credits": round(self.spent),
            "usd": round(self.spent * PRICING["usd_per_credit"], 4),
            "by_stage": by_stage,
        }
