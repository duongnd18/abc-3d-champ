"""Previews through `witness.render(source, RenderOptions)` (not model calls), split into one image per view.

render-service-js lays a grid out as cols = ceil(√n), rows = ceil(n / cols), img_size per cell, gap px between.
RenderRejected (the renderer refused the code) becomes Rejected for a repair; RenderUnavailable propagates.
"""

from __future__ import annotations

import io
import json
import math
from typing import Any

from PIL import Image
from witness_client import AsyncWitnessClient, RenderOptions, RenderRejected

View = tuple[str, float, float]  # (label, theta, phi); negative phi looks from above
JUDGE: tuple[View, ...] = (
    ("front_left", 30, 0),
    ("front_right", 330, 0),
    ("front_below", 0, 15),
    ("front_above", 0, -30),
)


class Rejected(Exception):
    """The renderer refused the code (checker rule, runtime exception, limit exceeded, …)."""

    def __init__(self, details: dict[str, Any]):
        self.details = details
        super().__init__(str(details.get("error", "rejected")))

    def problems(self) -> str:
        lines = [
            f"- [{f.get('stage', '?')}/{f.get('rule', '?')}] {f.get('detail', '')}"
            for f in (self.details.get("failures") or [])[:8]
            if isinstance(f, dict)
        ]
        return "\n".join(lines) or f"- {self.details.get('error', 'rejected')}"


async def render(
    witness: AsyncWitnessClient, source: str, views: tuple[View, ...], size: int, bg: str = "ffffff"
) -> dict[str, Image.Image]:
    opts = RenderOptions(
        thetas=tuple(float(v[1]) for v in views),
        phis=tuple(float(v[2]) for v in views),
        img_size=size,
        gap=0,
        bg_color=bg,
        lighting="neutral",
    )
    try:
        png = await witness.render(source, opts)
    except RenderRejected as e:
        raise Rejected(json.loads(e.detail_json)) from e
    grid = Image.open(io.BytesIO(png)).convert("RGB")
    cols = math.ceil(math.sqrt(len(views)))
    out = {}
    for i, (label, _, _) in enumerate(views):
        r, c = divmod(i, cols)
        out[label] = grid.crop((c * size, r * size, (c + 1) * size, (r + 1) * size))
    return out
