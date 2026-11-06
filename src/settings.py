"""Models, reasoning effort and output caps per role, and the pipeline's limits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    model: str
    effort: str  # low | medium | high
    max_output: int  # output token cap; also the worst case held in the ledger before a call
    verbosity: str | None = None  # text.verbosity (low | medium | high); None leaves the provider default
    tier: str = "default"  # service_tier


# service_tier of the Sol calls.
TIER = "priority"
# The orientation step's candidates (yaw, pitch); the first is the draft as built.
TURNS = ((0, 0), (45, 0), (-45, 0), (90, 0), (-90, 0), (180, 0), (0, 90), (0, -90))


@dataclass(frozen=True)
class Settings:
    # Runtime caps per prompt (docs/07 §3): 60 calls and 5,000,000 credits (= $5).
    calls: int = 60
    credits: float = 5_000_000
    reserve_calls: int = 1  # kept for a last repair

    plan: Role = Role("gpt-6.1-sol", "medium", 6_000, tier=TIER)  # notes and a checklist from the photo
    draft: Role = Role("gpt-6.1-sol", "high", 32_000, "high", TIER)  # every top entry drafts at high effort
    refine: Role = Role("gpt-6.1-sol", "high", 32_000, "high", TIER)
    repair: Role = Role("gpt-6.1-sol", "medium", 24_000, "high", TIER)
    pick: Role = Role("gpt-6.1-sol", "medium", 6_000, tier=TIER)  # scores all chain finals at once, both orders
    orient: Role = Role("gpt-6.1-sol", "low", 2_000, tier=TIER)  # which way to turn each chain's draft
    critic: Role = Role("gpt-6.1-sol", "medium", 6_000, tier=TIER)  # per-view problems before a rewrite (review=True)
    duel: Role = Role("gpt-6.1-sol", "medium", 6_000, tier=TIER)  # GLM's Stage 1 on one view: final check, pose

    # Typical: 1 plan + 3 × 3 + 2 pick + 3 rewrites + 8 final check (+ 8 pose check) = 26-34 calls. Calls are held
    # at their worst case before dispatch (decisions depend on recorded usage only, so a replay makes the same ones).
    chains: int = 3  # run concurrently, each with its own block of request ids
    # Different starting points, so the three drafts differ.
    starts: tuple[str, ...] = ("notes", "proportions", "plain")
    # Full rewrites per chain after the draft.
    refines: int = 2
    # Orientations (yaw, pitch) each draft may be turned to; ((0, 0),) keeps it as built.
    orients: tuple[tuple[int, int], ...] = ((0, 0),)
    orient_px: int = 256  # one view when the orientations are rendered and shown; the chosen one is re-rendered
    repairs: int = 1  # per chain and for the post-pick stage, for a module the renderer rejected
    chain_ids: int = 1000  # chain k uses request ids from (k + 1) * chain_ids
    sheet_px: int = 512  # side of one view in the refine sheet (the judge's Stage-1 views are 1024 px)
    pick_px: int = 512  # side of one view in the pick sheets
    # Pick: one call scores every chain final from its 4-view sheet, in both candidate orders (2 calls). pick_s1=True
    # asks the Stage-1 question per view for every pair instead (24 calls; measured no better than 2).
    pick_s1: bool = False
    pick_wave: int = 8  # Stage-1 pick calls sent at once
    post_refines: int = 3  # rewrites of the picked module
    # After the rewrites: the picked module against the last rewrite in GLM's Stage 1 (8 calls); the picked one comes
    # back only when it wins.
    final_check: bool = True
    # Pose candidates: extra tilts towards the camera (degrees) of the final module. A tilt whose colour layout matches
    # the photo better by more than pose_colour_gain (vision.ColourLayout, no model call) meets the module in GLM's
    # Stage 1 (8 calls) and replaces it only when it wins.
    pose_tilts: tuple[int, ...] = (10, 20)
    pose_colour_gain: float = 0.02
    # review=False rewrites with the checklist only, gate=False keeps every rewrite that renders.
    review: bool = False
    gate: bool = False
    critic_px: int = 512  # side of each labelled view shown to the reviewer
    # The gate (gate=True) drops the new module when its mean penalty over the 4 views is worse by gate_mean_gap or
    # more, or one view is worse by gate_view_gap or more.
    gate_mean_gap: float = 0.5
    gate_view_gap: float = 1.5
    # GLM's Stage-1 aggregation (judge-service multi_stage.py): a draw unless the mean penalties differ by more than
    # 0.7 and, with 3+ angles signed, at least 65% of the signed weight points the same way.
    s1_draw: float = 0.7
    s1_consistency: float = 0.65
    s1_min_signed: int = 3
    s1_both_bad: float = 8.0  # ... and a draw when both average 8+ and differ by 1.5 or less
    s1_both_bad_gap: float = 1.5
