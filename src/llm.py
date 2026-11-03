"""Model calls through `witness.responses.create(request_id=…, **params)`, charged to the prompt's ledger.

Request ids are issued in a fixed order before dispatch, so calls sent together with asyncio.gather keep the same
ids on replay; chains that run concurrently each draw ids from their own block (Calls.fork). Errors follow
docs/02 §4: a provider error drops the candidate; infrastructure errors (APIConnectionError, APITimeoutError) and
non-provider WitnessError (ReplayMismatch, …) propagate to the runner.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIError
from PIL import Image
from witness_client import AsyncWitnessClient, WitnessError

from src.budget import Ledger, credits
from src.settings import Role

Part = str | bytes  # text, or PNG bytes


def png_bytes(im: Image.Image, max_side: int | None = None) -> bytes:
    """Deterministic PNG encoding: the same image gives the same bytes, hence the same request on replay."""
    im = im.convert("RGB")
    if max_side and max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def _image_tokens(png: bytes) -> int:
    w, h = Image.open(io.BytesIO(png)).size
    return int(math.ceil(w / 32) * math.ceil(h / 32) * 1.3) + 100


def estimate_input(instructions: str, parts: list[Part]) -> int:
    text = len(instructions) + sum(len(p) for p in parts if isinstance(p, str))
    return int(text / 3.2) + sum(_image_tokens(p) for p in parts if isinstance(p, bytes)) + 200


@dataclass(frozen=True)
class Job:
    stage: str
    role: Role
    instructions: str
    parts: list[Part]
    schema: dict[str, Any] | None = None


@dataclass
class Ticket:
    stage: str
    role: Role
    request_id: int
    held: float


@dataclass
class Reply:
    text: str
    data: Any
    ok: bool
    request_id: int


class Calls:
    def __init__(self, witness: AsyncWitnessClient, ledger: Ledger, first_id: int = 0):
        self.witness, self.ledger = witness, ledger
        self._next_id = first_id

    def fork(self, first_id: int) -> Calls:
        """Same witness and ledger, request ids after `first_id`: concurrent chains keep the same ids on replay."""
        return Calls(self.witness, self.ledger, first_id)

    def ticket(
        self, stage: str, role: Role, instructions: str, parts: list[Part], *, use_reserve: bool = False
    ) -> Ticket:
        """Hold budget and issue the request id; call before dispatch, in a fixed order."""
        held = self.ledger.hold(
            stage, role.model, estimate_input(instructions, parts), role.max_output, use_reserve=use_reserve
        )
        self._next_id += 1
        return Ticket(stage, role, self._next_id, held)

    async def send(
        self, t: Ticket, instructions: str, parts: list[Part], schema: dict[str, Any] | None = None
    ) -> Reply:
        """Send one request. Provider error → ok=False (the call still counts); infrastructure error → raise."""
        content = [
            (
                {"type": "input_text", "text": p}
                if isinstance(p, str)
                else {
                    "type": "input_image",
                    "image_url": "data:image/png;base64," + base64.b64encode(p).decode("ascii"),
                    "detail": "high",
                }
            )
            for p in parts
        ]
        params: dict[str, Any] = {
            "model": t.role.model,
            "store": False,
            "service_tier": t.role.tier,
            "reasoning": {"effort": t.role.effort},
            "max_output_tokens": t.role.max_output,
            "instructions": instructions,
            "input": [{"role": "user", "content": content}],
        }
        text_options: dict[str, Any] = {}
        if schema:
            text_options["format"] = {
                "type": "json_schema",
                "name": schema["name"],
                "strict": True,
                "schema": schema["schema"],
            }
        if t.role.verbosity:
            text_options["verbosity"] = t.role.verbosity  # Codex clients default to low; long modules need high
        if text_options:
            params["text"] = text_options
        entry = {"stage": t.stage, "request_id": t.request_id, "model": t.role.model, "effort": t.role.effort}
        try:
            r = await self.witness.responses.create(request_id=t.request_id, **params)
        except APIConnectionError:
            raise  # infrastructure: the runner recovers this exchange
        except (WitnessError, APIError) as e:
            if isinstance(e, WitnessError) and getattr(e, "source", None) != "provider":
                raise  # includes ReplayMismatch
            self.ledger.settle(t.held, {**entry, "credits": t.held, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            return Reply("", None, False, t.request_id)
        u = r.usage
        n_in, n_out = (u.input_tokens, u.output_tokens) if u else (0, 0)
        cost = credits(t.role.model, n_in, n_out) if u else t.held
        status = r.status or "completed"
        self.ledger.settle(
            t.held, {**entry, "credits": cost, "input_tokens": n_in, "output_tokens": n_out, "status": status}
        )
        text = r.output_text or ""
        data = None
        if schema and status == "completed":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
        return Reply(text, data, status == "completed", t.request_id)

    async def ask(
        self,
        stage: str,
        role: Role,
        instructions: str,
        parts: list[Part],
        schema: dict[str, Any] | None = None,
        *,
        use_reserve: bool = False,
    ) -> Reply:
        t = self.ticket(stage, role, instructions, parts, use_reserve=use_reserve)
        return await self.send(t, instructions, parts, schema)

    async def batch(self, jobs: list[Job], wave: int) -> list[Reply]:
        """Send jobs in waves of `wave` calls; ids are issued for all jobs first, replies come back in job order."""
        tickets = [self.ticket(j.stage, j.role, j.instructions, j.parts) for j in jobs]
        out: list[Reply] = []
        for i in range(0, len(jobs), wave):
            group = zip(tickets[i : i + wave], jobs[i : i + wave])
            out += await asyncio.gather(*(self.send(t, j.instructions, j.parts, j.schema) for t, j in group))
        return out
