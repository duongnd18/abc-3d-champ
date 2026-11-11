"""The plan this submission runs.

Base: the round-3 leader, taohunter251/lark-ridge @20a6f557 ("r90a"), a fork of round-2 miner404 (SmoothTight/newvictor):
one lineage instead of two (the final pick between two lineages measured 50% on 27 judged pairs), the second lineage's
budget spent on four more gated steps (Astra high, three Sol xhigh); r70a budget reservation (budget.RESERVE_OUTPUT).
"""

from __future__ import annotations

from dataclasses import replace

from .pipeline import Draft, StagePlan, Step

# The leader's plan exactly as submitted (byte-identical requests and output; see tools/smoke.py).
LEADER_PLAN = StagePlan(drafts=(Draft(start='plain', model='gpt-6.1-sol', effort='high'), Draft(start='proportions', model='gpt-6.1-sol', effort='high'), Draft(start='plain', model='gpt-6.1-sol', effort='high'), Draft(start='proportions', model='gpt-6.1-sol', effort='high'), Draft(start='plain', model='gpt-6.1-sol', effort='high'), Draft(start='proportions', model='gpt-6.1-sol', effort='high')), steps=(Step(rewrites=(('gpt-6.1-sol', 'high'),), each_lineage=True, focus=('materials', 'shape')), Step(rewrites=(('gpt-6-astra', 'high'),), each_lineage=True, focus=('materials', 'shape')), Step(rewrites=(('gpt-6.1-sol', 'xhigh'),), each_lineage=True), Step(rewrites=(('gpt-6.1-sol', 'xhigh'),), each_lineage=True), Step(rewrites=(('gpt-6-astra', 'high'),), each_lineage=True), Step(rewrites=(('gpt-6.1-sol', 'xhigh'),), each_lineage=True), Step(rewrites=(('gpt-6-astra', 'high'),), each_lineage=True), Step(rewrites=(('gpt-6.1-sol', 'xhigh'),), each_lineage=True), Step(rewrites=(('gpt-6.1-sol', 'xhigh'),), each_lineage=True), Step(rewrites=(('gpt-6.1-sol', 'xhigh'),), each_lineage=True)), draft_keep=1, draft_each_start=True, pose=True, fill=0.99, glow=0.0, measured=False, outline_fit=False, outline_fit_last=True)

# Other plans are selected with `python local.py --plan NAME`; the submission runs ACTIVE_PLAN.
SOL_HIGH = ("gpt-6.1-sol", "high")

# R4_BASE_PLAN: the leader without its two finishing passes that the round-3 duels show do not pay (the 22-degree photo
# tilt and METAL_PASS), plus our neutral-light texts (metal recipe 0.85-1.0, no "lower the metalness" rewrite item, no
# "turned black" selector flaw), and no panel for a step whose rewrite gave no module. Every request changes (the
# generator text changes). Not yet judged.
R4_BASE_PLAN = replace(LEADER_PLAN, photo_tilt=False, metal_pass=False, neutral_texts=True, skip_lonely_panel=True)

# R4_PLAN: 3 drafts instead of 6, one per start (plain, proportions, and crown's inventory: list every visible part with
# count, color and material before building it), and the saved budget spent on 4 more gated Sol-high rewrites after the
# leader's 10 (steps 11-14, rewrite ids 1100-1400, panels 9110-9140).
# Budget simulation (outputs/r2-neutral costs, the r70a reservation rule): an average prompt runs 13 of the 14 steps
# (the leader 10), a cheap one all 14, an expensive one (x1.25-1.5 cost) 8-9 (the leader 6-8); steps the budget refuses
# are skipped without a panel. Not yet judged.
R4_PLAN = replace(R4_BASE_PLAN, drafts=tuple(Draft(start=start, model="gpt-6.1-sol", effort="high")
                                             for start in ("plain", "proportions", "inventory")),
                  steps=LEADER_PLAN.steps + tuple(Step(rewrites=(SOL_HIGH,), each_lineage=True) for _ in range(4)))

# R4_SOL_PLAN (to test, not active): R4_PLAN with the leader's three Astra steps on Sol high (an Astra rewrite costs
# about 4.6 Sol-high rewrites; crown's round-3 notes: Sol high per call no worse than xhigh or Astra) and 6 extra steps
# instead of 4. Simulated: 16 steps on an average prompt, 15 on an expensive one, about 55 calls.
R4_SOL_PLAN = replace(R4_PLAN, steps=tuple(
    replace(step, rewrites=tuple(SOL_HIGH if model == "gpt-6-astra" else (model, effort) for model, effort in step.rewrites))
    for step in LEADER_PLAN.steps) + tuple(Step(rewrites=(SOL_HIGH,), each_lineage=True) for _ in range(6)))

# R4_STRETCH_PLAN: R4_PLAN plus the stretch finish (x1.15).
R4_STRETCH_PLAN = replace(R4_PLAN, stretch=1.15)

# Router (route.py, StagePlan.routed / routed_tilt / food_plan) with the stretch finish. One cheap call classifies the
# photo before the drafts. Upright structures, and tall photos that are not food, keep the module level; flat objects and
# food get the 22-degree photo tilt (on either base). Food continues on two lineages through the first six steps, and
# every prompt gets the stretch. The food plan is built from the routed plan, so it keeps the same finish settings.
ROUTER_STRETCH = 1.15
_R4_ROUTED = replace(R4_PLAN, routed=True, routed_tilt=True, stretch=ROUTER_STRETCH)
R4_ROUTED_PLAN = replace(_R4_ROUTED, food_plan=replace(_R4_ROUTED, draft_keep=2, steps=R4_PLAN.steps[:6]))
# LEADER_ROUTED_PLAN: the configuration the router was measured on (the leader plus the router and the stretch). It sends
# the same requests and returns the same modules as the router build it was ported from (cache-replay check).
_LEADER_ROUTED = replace(LEADER_PLAN, routed=True, routed_tilt=True, stretch=ROUTER_STRETCH)
LEADER_ROUTED_PLAN = replace(_LEADER_ROUTED, food_plan=replace(_LEADER_ROUTED, draft_keep=2, steps=LEADER_PLAN.steps[:6]))

ACTIVE_PLAN = R4_ROUTED_PLAN
