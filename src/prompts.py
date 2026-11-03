"""Prompt texts from src/prompts/ and the JSON schemas of the structured calls.

Templates use str.format: {name} is a field. Design sources: docs/NGUON_Y_TUONG.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

DIR = Path(__file__).with_name("prompts")
SPEC = Path(__file__).resolve().parents[1] / "instructions.md"  # official output specification (base worker)


def md(name: str) -> str:
    return (DIR / name).read_text().rstrip("\n")


JUDGE_FACTS = md("judge_facts.md")
CODER_SYSTEM = (
    md("coder_system.md")
    .replace("{JUDGE_FACTS}", JUDGE_FACTS)
    .replace("{PLAYBOOK}", md("playbook.md"))
    .replace("{HELPERS}", (DIR / "helpers.js").read_text().rstrip())
    .replace("{RULES}", SPEC.read_text().rstrip())
)
JUDGE_SYSTEM = md("judge_system.md")  # GLM's Stage-1 system prompt, verbatim (judge-service multi_stage.py)
PLAN_SYSTEM = (
    "You study one reference photo of an object before it is rebuilt as a procedural 3D model. "
    "Respond with the requested JSON."
)
PLAN, DRAFT, REFINE, REPAIR, PICK = md("plan.md"), md("draft.md"), md("refine.md"), md("repair.md"), md("pick.md")
DRAFT_PROPORTIONS, CRITIC, ORIENT = md("draft_proportions.md"), md("critic.md"), md("orient.md")
S1 = md("s1.md")  # GLM's Stage-1 per-view prompt, verbatim (judge-service multi_stage.py S1_PROMPT_MATCH_USER)
S1_ANGLE_DESC = {  # verbatim, multi_stage.py
    "front_left": "slightly left of the front",
    "front_right": "slightly right of the front",
    "front_below": "the front, from slightly below",
    "front_above": "the front, from slightly above",
}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


_TEXT: dict[str, Any] = {"type": "string"}
_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
PLAN_SCHEMA: dict[str, Any] = {
    "name": "photo_plan",
    "schema": _obj(
        {
            "object": _TEXT,
            "visible_side": _TEXT,
            "proportions_w_h_d": _TEXT,
            "parts": _LIST,
            "text": _TEXT,
            "checklist": _LIST,
        }
    ),
}
CRITIC_SCHEMA: dict[str, Any] = {
    "name": "review",
    "schema": _obj(
        {"front_left": _LIST, "front_right": _LIST, "front_below": _LIST, "front_above": _LIST, "keep": _LIST}
    ),
}
ORIENT_SCHEMA: dict[str, Any] = {"name": "orient", "schema": _obj({"best": {"type": "integer"}, "reason": _TEXT})}
VIEW_NAMES = {  # how the prompts name the judge's views
    "front_left": "front-left 30°",
    "front_right": "front-right 30°",
    "front_below": "from the front 15° below",
    "front_above": "from the front 30° above",
}


def items_of(values: Any, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    return [" ".join(str(v).split()) for v in values if str(v).strip()][:limit]


def bullets(values: list[str]) -> str:
    return "\n".join(f"- {v}" for v in values)


def checklist_of(plan: dict[str, Any]) -> list[str]:
    return items_of(plan.get("checklist"), 7)


def notes_block(plan: dict[str, Any]) -> str:
    """The plan as notes in front of a draft (the photo wins where they disagree)."""
    if not plan:
        return ""
    lines = ["Notes from a first look at the photo (the photo wins where they disagree):"]
    for key, label in (("object", "Object"), ("visible_side", "Visible side"), ("proportions_w_h_d", "W : H : D")):
        value = " ".join(str(plan.get(key) or "").split())
        if value:
            lines.append(f"{label}: {value}")
    parts = items_of(plan.get("parts"), 14)
    if parts:
        lines += ["Parts:", bullets(parts)]
    text = " ".join(str(plan.get("text") or "").split())
    if text:
        lines.append(f"Text: {text}")
    check = checklist_of(plan)
    if check:
        lines += ["Checklist:", bullets(check)]
    return "\n".join(lines) + "\n\n"


def checklist_block(check: list[str]) -> str:
    """The plan's checklist after a rewrite prompt."""
    if not check:
        return ""
    return (
        "Checklist from a first look at the photo (the photo wins where they disagree); make sure each item "
        "matches:\n" + bullets(check) + "\n\n"
    )


def features_block(check: list[str]) -> str:
    """The plan's checklist for the pick and the reviewer."""
    if not check:
        return ""
    return (
        "Features a faithful model should match (from a first look at the reference; the reference wins where "
        "they disagree):\n" + bullets(check) + "\n\n"
    )


def review_block(review: dict[str, Any]) -> str:
    """The reviewer's per-view problems, for the rewrite that follows it."""
    lines = []
    for label, name in VIEW_NAMES.items():
        problems = items_of(review.get(label), 4)
        if problems:
            lines += [f"{name}:", bullets(problems)]
    if not lines:
        return ""
    keep = items_of(review.get("keep"), 5)
    out = (
        "A reviewer compared these four views with the photo. Problems that cost duels, per view; fix every one "
        "(one view that is clearly worse than the rival's turns a win into a draw):\n" + "\n".join(lines) + "\n"
    )
    if keep:
        out += "Already right, keep unchanged:\n" + bullets(keep) + "\n"
    return out + "\n"


PICK_SCHEMA: dict[str, Any] = {
    "name": "panel",
    "schema": _obj({"penalties": {"type": "array", "items": {"type": "number"}}}),
}
S1_SCHEMA: dict[str, Any] = {
    "name": "s1",
    "schema": _obj({"penalty_1": {"type": "integer"}, "penalty_2": {"type": "integer"}, "issues": {"type": "string"}}),
}
