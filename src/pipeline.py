"""Image → Three.js module.

  1 plan: notes on the photo (object, visible side, proportions, parts, text) and a short checklist
  2 three chains, concurrently, from different starting points: a draft (high effort), then full rewrites that see the
    photo, a close-up crop of the object and the module rendered from the judge's 4 views; a module the renderer
    rejects gets a repair call
  3 pick one of the chain finals: one call scores them all, both candidate orders
  4 more full rewrites of the picked module, then one check: the picked module against the last rewrite in GLM's
    Stage 1; the picked one comes back only when it wins
  5 pose: extra tilts towards the camera, screened by colour layout (no model call), checked in Stage 1
  6 output (a measured fallback if nothing ever rendered)

Every decision depends only on model replies, renders and recorded usage (no clocks, no completion order): each
chain draws request ids from its own block, the later stages run one call batch at a time, renders run one at a
time, and every call is held at its worst case before dispatch. A replay sends the same requests and returns the
same JavaScript bytes.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from openai import APIConnectionError
from PIL import Image
from witness_client import AsyncWitnessClient, RenderUnavailable, WitnessError

from src import prompts as P
from src import vision as V
from src.budget import BudgetExceeded, Ledger, credits
from src.llm import Calls, Job, Part, estimate_input, png_bytes
from src.module import Pose, assemble, extract_build, fallback_build
from src.render import JUDGE, Rejected, render
from src.settings import Role, Settings

logger = logging.getLogger(__name__)

# Errors the runner must see (docs/02 §4, docs/07 §2); any other exception is a bug of ours and keeps the best so far.
PROPAGATE = (APIConnectionError, WitnessError, RenderUnavailable)
_VERTICES = re.compile(r"VERTEX_LIMIT_EXCEEDED\] (\d+) >")
OVER_LIMIT_NOTE = (
    "Your current module is over the 250,000-vertex limit; these renders show it after its costliest small parts "
    "were dropped to fit. Keep the new version under 150,000 vertices (InstancedMesh for repeated parts, lower "
    "segment counts)."
)


def repair_advice(problems: str) -> str:
    """A concrete target when the module has too many vertices (repairs left alone cut too little)."""
    m = _VERTICES.search(problems)
    if not m:
        return ""
    n = int(m.group(1))
    return (
        f"\nThe module has {n:,} vertices and the limit is 250,000: cut it to about 150,000 (divide by "
        f"{n / 150_000:.1f}). Lower the segment counts (8-16 for small round parts, 32-48 for big ones), build every "
        "repeated part as one geometry in an InstancedMesh (instances add no vertices), share geometries and drop "
        "parts hidden inside the object.\n"
    )


Angle = tuple[float, float]  # (pen_a, pen_b) of one view, averaged over both seat orders


def s1_result(angles: list[Angle], S: Settings) -> str:
    """GLM's Stage-1 aggregation (judge-service multi_stage.py _s1_aggregate): 'A', 'B' or 'draw'."""
    if not angles:
        return "draw"
    pa, pb = (sum(x[k] for x in angles) / len(angles) for k in (0, 1))
    signed = [x for x in angles if x[0] != x[1]]
    w_a = sum(1 for x in signed if x[0] < x[1])
    consistency = abs(2 * w_a - len(signed)) / len(signed) if signed else 1.0
    split = len(signed) >= S.s1_min_signed and consistency < S.s1_consistency
    both_bad = (pa + pb) / 2 >= S.s1_both_bad and abs(pa - pb) <= S.s1_both_bad_gap
    if abs(pa - pb) <= S.s1_draw or split or both_bad:
        return "draw"
    return "A" if pa < pb else "B"


def keep_new(angles: list[Angle], S: Settings) -> bool:
    """Gate after a post-pick rewrite, angles = (old, new): keep the new module unless the old one is clearly better
    on average or on any single view (one clearly worse view turns a duel into a draw)."""
    if not angles:
        return True
    worse = [new - old for old, new in angles]
    return sum(worse) / len(worse) < S.gate_mean_gap and max(worse) < S.gate_view_gap


def sheet_of(front: dict[str, Image.Image], px: int) -> Image.Image:
    """The judge's 4 views as a 2x2 sheet, px per view."""
    g = Image.new("RGB", (2 * px, 2 * px), "white")
    for i, (label, _, _) in enumerate(JUDGE):
        g.paste(front[label].resize((px, px), Image.Resampling.LANCZOS), ((i % 2) * px, (i // 2) * px))
    return g


@dataclass
class Version:
    id: str
    build: str
    front: dict[str, Image.Image]  # the judge's 4 Stage-1 views
    chain: int  # S.chains for the post-pick stage
    step: int  # 0 = draft, then one per rewrite
    cap: bool = False  # rendered with the vertex cap (still over the limit after its repair)
    yaw: int = 0  # orientation the module is rendered and submitted in (degrees, Pose)
    pitch: int = 0
    tilt: int = 0  # extra tilt towards the camera from the pose step (degrees, Pose)

    def sheet(self, px: int) -> Image.Image:
        return sheet_of(self.front, px)


@dataclass
class Run:
    image: bytes
    seed: int
    witness: AsyncWitnessClient
    S: Settings = field(default_factory=Settings)

    def __post_init__(self) -> None:
        self.ledger = Ledger(self.S.calls, self.S.credits, self.S.reserve_calls)
        self.calls = Calls(self.witness, self.ledger)
        self.photo = Image.open(io.BytesIO(self.image)).convert("RGB")
        self.photo_png = png_bytes(self.photo, 1024)
        closeup = V.object_closeup(self.photo)
        self.closeup_png = png_bytes(closeup) if closeup is not None else None
        self.colours: V.ColourLayout | None = None
        self.events: list[dict[str, Any]] = []
        self.versions: list[Version] = []
        self.chain_final: dict[int, Version] = {}  # the last module that rendered, per chain
        self.orient: dict[int, tuple[int, int]] = {}  # (yaw, pitch) per chain; slot S.chains = the picked module's
        self.plan: dict[str, Any] = {}
        self.checklist: list[str] = []
        self.repairs_left = [self.S.repairs] * (self.S.chains + 1)  # the last slot is the post-pick stage's
        self.render_lock = asyncio.Lock()  # one render at a time: a render over 30 s fails as RenderUnavailable
        self.best: Version | None = None  # the module that would be submitted now
        self.final: Version | None = None

    def note(self, kind: str, **kw: Any) -> None:
        self.events.append({"kind": kind, **kw})
        logger.info("%s %s", kind, json.dumps(kw, ensure_ascii=False, default=str)[:600])

    # ---- 1. plan ----------------------------------------------------------------------------------------------------
    async def make_plan(self) -> None:
        r = await self.calls.ask("plan", self.S.plan, P.PLAN_SYSTEM, [*self.photo_parts(), P.PLAN], P.PLAN_SCHEMA)
        self.plan = r.data if isinstance(r.data, dict) else {}
        self.checklist = P.checklist_of(self.plan)
        self.note(
            "plan",
            object=self.plan.get("object"),
            checklist=len(self.checklist),
        )

    # ---- deterministic: assemble → renderer (rules + render) → render checks --------------------------------------
    async def realize(self, vid: str, build: str, chain: int, step: int, cap: bool = False) -> Version | str:
        """A valid Version, or a description of the problems for a repair call."""
        yaw, pitch = self.orient.get(chain, (0, 0))
        async with self.render_lock:
            try:
                source = assemble(build, Pose(yaw=yaw, pitch=pitch, cap=cap))
                front = await render(self.witness, source, JUDGE, self.S.sheet_px)
            except Rejected as e:
                return e.problems()
        issues = V.checks(front, None)
        if issues and issues[0].startswith("EMPTY"):
            return "- " + issues[0]
        v = Version(vid, build, front, chain, step, cap, yaw, pitch)
        self.versions.append(v)
        return v

    async def settle(self, calls: Calls, vid: str, build: str | None, chain: int, step: int) -> Version | None:
        """Render a module; a rejected one gets repair calls while its chain (or stage) has repairs left."""
        if build is None:
            self.note("no_code", id=vid)
            return None
        res = await self.realize(vid, build, chain, step)
        while isinstance(res, str) and self.repairs_left[chain] > 0:
            self.repairs_left[chain] -= 1
            text = P.REPAIR.format(problems=res, advice=repair_advice(res), code=build)
            r = await calls.ask("repair", self.S.repair, P.CODER_SYSTEM, [text])
            fixed = extract_build(r.text) if r.ok else None
            self.note("repair", id=vid, problems=res[:300], fixed=fixed is not None)
            if fixed is None:
                break
            build = fixed
            res = await self.realize(vid, build, chain, step)
        if isinstance(res, str) and _VERTICES.search(res):  # still too many vertices: drop the costliest parts
            self.note("vertex_cap", id=vid, problems=res[:200])
            res = await self.realize(vid, build, chain, step, cap=True)
        if isinstance(res, str):
            self.note("invalid", id=vid, problems=res[:300])
            return None
        return res

    def photo_parts(self) -> list[Part]:
        """The photo, then (when the object does not already fill it) a close-up crop of the object at 1024 px."""
        if self.closeup_png is None:
            return [self.photo_png]
        return [self.photo_png, "Close-up of the object (a crop of the same photo):", self.closeup_png]

    def refine_parts(self, v: Version, notes: str) -> list[Part]:
        return [
            *self.photo_parts(),
            png_bytes(v.sheet(self.S.sheet_px)),
            *([OVER_LIMIT_NOTE] if v.cap else []),
            P.REFINE.format(notes=notes, code=v.build),
        ]

    # ---- 2. one chain: draft → S.refines rewrites -------------------------------------------------------------------
    def draft_prompt(self, k: int) -> str:
        start = self.S.starts[k % len(self.S.starts)]
        if start == "notes":
            return P.notes_block(self.plan) + P.DRAFT
        if start == "proportions":
            return P.checklist_block(self.checklist) + P.DRAFT_PROPORTIONS
        return P.DRAFT

    async def turn(self, calls: Calls, v: Version, k: int) -> Version:
        """Render the draft in each of S.orients and ask, in both candidate orders, which one shows the object the way
        the photo does in all four views (judged by its worst view). The draft turns only when both orders pick the
        same other orientation; the chain then keeps that orientation for its rewrites."""
        S = self.S
        cands: list[tuple[int, dict[str, Image.Image]]] = [(0, v.front)]  # (index into S.orients, the 4 views)
        for o, (yaw, pitch) in enumerate(S.orients[1:], 1):
            async with self.render_lock:  # small renders: 7 per chain, one at a time
                try:
                    source = assemble(v.build, Pose(yaw=yaw, pitch=pitch, cap=v.cap))
                    front = await render(self.witness, source, JUDGE, S.orient_px)
                except Rejected:
                    continue
            if not (V.checks(front, None) or [""])[0].startswith("EMPTY"):
                cands.append((o, front))
        n = len(cands)
        if n == 1:
            return v
        sheets = [png_bytes(sheet_of(front, S.orient_px)) for _, front in cands]
        orders = [list(range(n)), list(reversed(range(n)))]
        jobs = []
        for order in orders:
            parts: list[Part] = ["Image 1: reference photo.", self.photo_png]
            for j, i in enumerate(order):
                parts += [f"Image {j + 2}: candidate {j + 1}.", sheets[i]]
            parts.append(P.ORIENT.format(last=n + 1))
            jobs.append(Job("orient", S.orient, P.JUDGE_SYSTEM, parts, P.ORIENT_SCHEMA))
        replies = await calls.batch(jobs, 2)
        picks: list[int | None] = []
        for order, r in zip(orders, replies):
            b = r.data.get("best") if isinstance(r.data, dict) else None
            picks.append(order[b - 1] if isinstance(b, int) and 1 <= b <= n else None)
        chosen = picks[0] if picks[0] is not None and picks[0] == picks[1] else 0
        self.note(
            "orient",
            id=v.id,
            picks=[S.orients[cands[p][0]] if p is not None else None for p in picks],
            turned=S.orients[cands[chosen][0]] if chosen else None,
        )
        if not chosen:
            return v
        self.orient[k] = S.orients[cands[chosen][0]]
        turned = await self.realize(f"c{k}o", v.build, k, v.step, v.cap)  # full-size views for the rewrite sheet
        if isinstance(turned, str):  # it rendered in this orientation a moment ago; keep the draft as built
            del self.orient[k]
            return v
        return turned

    async def chain(self, k: int) -> None:
        S = self.S
        calls = self.calls.fork((k + 1) * S.chain_ids)
        r = await calls.ask("draft", S.draft, P.CODER_SYSTEM, [*self.photo_parts(), self.draft_prompt(k)])
        current = await self.settle(calls, f"c{k}d", extract_build(r.text) if r.ok else None, k, 0)
        if current is not None:
            current = await self.turn(calls, current, k)
        for step in range(1, S.refines + 1):
            if current is None:
                return
            self.chain_final[k] = current
            notes = P.checklist_block(self.checklist)
            r = await calls.ask("refine", S.refine, P.CODER_SYSTEM, self.refine_parts(current, notes))
            v = await self.settle(calls, f"c{k}r{step}", extract_build(r.text) if r.ok else None, k, step)
            self.note(
                "refined", id=f"c{k}r{step}", valid=v is not None, kb=round(len(v.build) / 1024, 1) if v else None
            )
            current = v or current
        if current is not None:
            self.chain_final[k] = current

    # ---- 3. one call scores the chains' modules on the judge's views, both candidate orders -----------------------
    async def pick(self, cands: list[Version]) -> Version:
        S, n = self.S, len(cands)
        default = cands[0]  # the lowest chain: the plan's notes
        if n == 1:
            return default
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        asks = 2 * len(JUDGE) * len(pairs)
        one = self.worst_case(S.duel, P.JUDGE_SYSTEM, self.gate_parts(default, default, JUDGE[0][0]))
        if S.pick_s1 and self.ledger.can(asks, asks * one):
            return await self.pick_s1(cands, pairs)
        sheets = [png_bytes(v.sheet(S.pick_px)) for v in cands]
        orders = [list(range(n)), list(reversed(range(n)))]
        jobs = []
        for order in orders:
            parts: list[Part] = ["Image 1: reference photo.", self.photo_png]
            for j, i in enumerate(order):
                parts += [f"Image {j + 2}: candidate {j + 1}.", sheets[i]]
            parts.append(P.PICK.format(last=n + 1, features=P.features_block(self.checklist)))
            jobs.append(Job("pick", S.pick, P.JUDGE_SYSTEM, parts, P.PICK_SCHEMA))
        replies = await self.calls.batch(jobs, 2)
        total, seen = [0.0] * n, [0] * n
        for order, r in zip(orders, replies):
            pens = r.data.get("penalties") if isinstance(r.data, dict) else None
            if not isinstance(pens, list) or len(pens) != n:
                continue
            for j, i in enumerate(order):
                total[i] += float(pens[j])
                seen[i] += 1
        if not any(seen):
            self.note("pick", failed=True, best=default.id)
            return default
        score = [total[i] / seen[i] if seen[i] else 99.0 for i in range(n)]
        best = min(range(n), key=lambda i: (score[i], cands[i].chain))
        self.note("pick", scores={v.id: round(s, 2) for v, s in zip(cands, score)}, best=cands[best].id)
        return cands[best]

    async def pick_s1(self, cands: list[Version], pairs: list[tuple[int, int]]) -> Version:
        """GLM's Stage-1 question for every pair, view and seat order; the lowest total penalty wins (every finalist
        is asked about equally often). An unreadable reply counts 5 for both."""
        S, n = self.S, len(cands)
        seats = [(x, y, label) for i, j in pairs for label, _, _ in JUDGE for x, y in ((i, j), (j, i))]
        jobs = [
            Job("pick", S.duel, P.JUDGE_SYSTEM, self.gate_parts(cands[x], cands[y], label), P.S1_SCHEMA)
            for x, y, label in seats
        ]
        replies = await self.calls.batch(jobs, S.pick_wave)
        total = [0.0] * n
        for (x, y, _), r in zip(seats, replies):
            d = r.data if isinstance(r.data, dict) else {}
            total[x] += float(d["penalty_1"]) if isinstance(d.get("penalty_1"), (int, float)) else 5.0
            total[y] += float(d["penalty_2"]) if isinstance(d.get("penalty_2"), (int, float)) else 5.0
        best = min(range(n), key=lambda i: (total[i], cands[i].chain))
        self.note("pick", s1=True, totals={v.id: round(t, 1) for v, t in zip(cands, total)}, best=cands[best].id)
        return cands[best]

    # ---- 4. reviewed, gated rewrites of the picked module -----------------------------------------------------------
    @staticmethod
    def worst_case(role: Role, instructions: str, parts: list[Part]) -> float:
        return credits(role.model, estimate_input(instructions, parts), role.max_output)

    def pass_fits(self, v: Version) -> bool:
        """Start a pass only when review, rewrite, one repair and the gate all fit at their worst case."""
        S = self.S
        calls = 2  # rewrite + a possible repair
        est = 2 * self.worst_case(S.refine, P.CODER_SYSTEM, self.refine_parts(v, "x" * 4000))
        if S.review:
            calls += 1
            est += self.worst_case(S.critic, P.JUDGE_SYSTEM, self.review_parts(v))
        if S.gate:
            calls += 2 * len(JUDGE)
            est += 2 * len(JUDGE) * self.worst_case(S.duel, P.JUDGE_SYSTEM, self.gate_parts(v, v, JUDGE[0][0]))
        return self.ledger.can(calls, est)

    def review_parts(self, v: Version) -> list[Part]:
        parts: list[Part] = ["Image 1: reference photo.", self.photo_png]
        for i, (label, _, _) in enumerate(JUDGE):
            im = v.front[label].resize((self.S.critic_px, self.S.critic_px), Image.Resampling.LANCZOS)
            parts += [f"Image {i + 2}: {P.VIEW_NAMES[label]}.", png_bytes(im)]
        parts.append(P.CRITIC.format(features=P.features_block(self.checklist)))
        return parts

    def gate_parts(self, x: Version, y: Version, label: str) -> list[Part]:
        return [
            "Reference image (target object):",
            self.photo_png,
            "3D model 1:",
            png_bytes(x.front[label]),
            "3D model 2:",
            png_bytes(y.front[label]),
            P.S1.format(angle_desc=P.S1_ANGLE_DESC[label]),
        ]

    async def compare(self, a: Version, b: Version) -> list[Angle]:
        """GLM's Stage 1 between two versions: per view (pen_a, pen_b) over both seat orders, dropping the views
        whose two orders contradict each other (judge-service multi_stage.py)."""
        jobs = []
        for label, _, _ in JUDGE:
            for x, y in ((a, b), (b, a)):
                jobs.append(Job("gate", self.S.duel, P.JUDGE_SYSTEM, self.gate_parts(x, y, label), P.S1_SCHEMA))
        replies = await self.calls.batch(jobs, 4)
        angles: list[Angle] = []
        for i in range(len(JUDGE)):
            ab, ba = (r.data if isinstance(r.data, dict) else None for r in replies[2 * i : 2 * i + 2])
            if not ab or not ba or "penalty_1" not in ab or "penalty_1" not in ba:
                continue
            d_ab = float(ab["penalty_1"]) - float(ab["penalty_2"])  # a minus b, a in seat 1
            d_ba = float(ba["penalty_2"]) - float(ba["penalty_1"])  # a minus b, a in seat 2
            if d_ab * d_ba < 0:
                continue
            angles.append(((ab["penalty_1"] + ba["penalty_2"]) / 2, (ab["penalty_2"] + ba["penalty_1"]) / 2))
        return angles

    async def improve(self) -> None:
        """Up to S.post_refines passes of review → rewrite → gate on self.best (updated as soon as a pass is kept)."""
        S, post = self.S, self.S.chains
        for k in range(1, S.post_refines + 1):
            best = self.best
            if best is None:
                return
            if not self.pass_fits(best):
                self.note("post_stop", reason="budget", passes=k - 1)
                return
            review: dict[str, Any] = {}
            if S.review:
                r = await self.calls.ask("critic", S.critic, P.JUDGE_SYSTEM, self.review_parts(best), P.CRITIC_SCHEMA)
                review = r.data if isinstance(r.data, dict) else {}
            problems = {label: len(P.items_of(review.get(label), 4)) for label, _, _ in JUDGE}
            notes = P.review_block(review) + P.checklist_block(self.checklist)
            r = await self.calls.ask("post_refine", S.refine, P.CODER_SYSTEM, self.refine_parts(best, notes))
            new = await self.settle(self.calls, f"p{k}", extract_build(r.text) if r.ok else None, post, best.step + 1)
            if new is None:
                self.note("post_refine", n=k, valid=False, problems=problems)
                continue
            angles = await self.compare(best, new) if S.gate else []
            kept = keep_new(angles, S)  # no gate: every rewrite that renders is kept
            self.note(
                "gate",
                n=k,
                old=best.id,
                new=new.id,
                problems=problems,
                views=[(round(a, 1), round(b, 1)) for a, b in angles],
                s1=s1_result(angles, S),
                kept="new" if kept else "old",
                kb=round(len(new.build) / 1024, 1),
            )
            if kept:
                self.best = new

    def check_fits(self, v: Version) -> bool:
        n = 2 * len(JUDGE)
        return self.ledger.can(n, n * self.worst_case(self.S.duel, P.JUDGE_SYSTEM, self.gate_parts(v, v, JUDGE[0][0])))

    async def final_check(self, picked: Version) -> None:
        """The picked module against the last rewrite (GLM's Stage 1, both seat orders); the rewrites are dropped only
        when the picked module wins."""
        best = self.best
        if not self.S.final_check or best is None or best is picked:
            return
        if not self.check_fits(best):
            self.note("final_check", skipped="budget")
            return
        angles = await self.compare(picked, best)
        verdict = s1_result(angles, self.S)
        self.note(
            "final_check",
            picked=picked.id,
            last=best.id,
            views=[(round(a, 1), round(b, 1)) for a, b in angles],
            s1=verdict,
            kept=picked.id if verdict == "A" else best.id,
        )
        if verdict == "A":
            self.best = picked

    # ---- 5. pose: extra tilts towards the camera, screened by colour layout, checked in Stage 1 --------------------
    async def pose(self) -> None:
        S, best = self.S, self.best
        if best is None or not S.pose_tilts:
            return
        if self.colours is None:
            self.colours = V.ColourLayout(self.photo)
        if not self.colours.ok:
            return
        base = self.colours.score(best.front)
        cands: list[tuple[float, int, dict[str, Image.Image]]] = []
        for t in S.pose_tilts:
            async with self.render_lock:
                try:
                    pose = Pose(yaw=best.yaw, pitch=best.pitch, cap=best.cap, tilt=best.tilt + t)
                    front = await render(self.witness, assemble(best.build, pose), JUDGE, S.sheet_px)
                except Rejected:
                    continue
            if not (V.checks(front, None) or [""])[0].startswith("EMPTY"):
                cands.append((self.colours.score(front) - base, t, front))
        passed = [c for c in cands if c[0] > S.pose_colour_gain]
        self.note("pose_colour", base=round(base, 3), gains={t: round(g, 3) for g, t, _ in cands})
        if not passed:
            return
        gain, t, front = max(passed, key=lambda c: (c[0], -c[1]))
        cand = Version(f"{best.id}t{t}", best.build, front, best.chain, best.step, best.cap, best.yaw, best.pitch,
                       best.tilt + t)
        if not self.check_fits(best):
            self.note("pose", skipped="budget")
            return
        angles = await self.compare(best, cand)
        verdict = s1_result(angles, S)
        self.note(
            "pose",
            tilt=t,
            colour_gain=round(gain, 3),
            views=[(round(a, 1), round(b, 1)) for a, b in angles],
            s1=verdict,
            kept=cand.id if verdict == "B" else best.id,
        )
        if verdict == "B":
            self.versions.append(cand)
            self.best = cand

    # ---- whole prompt -----------------------------------------------------------------------------------------------
    async def execute(self) -> str | None:
        try:
            await self.make_plan()
            results = await asyncio.gather(*(self.chain(k) for k in range(self.S.chains)), return_exceptions=True)
            for res in results:
                if isinstance(res, PROPAGATE):
                    raise res
                if isinstance(res, BudgetExceeded):
                    self.note("budget_stop", error=str(res))
                elif isinstance(res, BaseException):
                    logger.error("chain error: %s: %s", type(res).__name__, res)
                    self.note("error", error=f"{type(res).__name__}: {res}"[:300])
            cands = [self.chain_final[k] for k in sorted(self.chain_final)]
            if cands:
                self.best = cands[0]
                self.best = picked = await self.pick(cands)
                self.orient[self.S.chains] = (self.best.yaw, self.best.pitch)
                await self.improve()
                await self.final_check(picked)
                await self.pose()
        except BudgetExceeded as e:
            self.note("budget_stop", error=str(e))
        except PROPAGATE:
            raise
        except Exception as e:
            logger.exception("pipeline error; returning the best model so far")
            self.note("error", error=f"{type(e).__name__}: {e}"[:300])
        best = self.final = self.best
        self.note("final", id=best.id if best else None, **self.ledger.summary())
        if best is not None:
            return assemble(best.build, Pose(yaw=best.yaw, pitch=best.pitch, cap=best.cap, tilt=best.tilt))
        return assemble(fallback_build(V.measure_photo(self.photo)), Pose())  # nothing ever rendered


async def generate(image: bytes, seed: int, witness: AsyncWitnessClient) -> str | None:
    return await Run(image, seed, witness).execute()
