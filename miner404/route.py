"""Which levers a prompt gets, from one cheap look at the photo. Everything else stays on the plan; a reply that cannot
be read, or a call the budget refuses, leaves every lever off.

  upright: a building, structure or piece of furniture standing on the ground. The final photo tilt is skipped: it is
           chosen on a level view the judge never shows, and the judge's side views then show the structure leaning.
  food:    real food or a dish. After the drafts the prompt continues on the plan's food plan (two lineages through
           fewer steps instead of one lineage through all of them).

A lever needs the category and its own yes/no to agree, because a wrong switch costs more than a missed one: a missed
prompt simply runs the plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CATEGORIES = ("vehicle", "furniture", "food", "animal", "human_or_character", "weapon_or_tool", "building_or_structure",
              "plant", "container_or_vessel", "electronics_or_device", "jewelry_or_accessory", "toy_or_figurine",
              "instrument", "other")
UPRIGHT_CATEGORIES = ("furniture", "building_or_structure")

INSTRUCTIONS = """Classify the main object of a product-style photo that must be rebuilt as a 3D model. Reply with the
JSON schema only.

category: the single best category for the main object.
upright_structure: true only when the main object is a building, a structure or a piece of furniture that stands upright
on the ground or the floor (a house, tower, shed, bookcase, cabinet, wardrobe, chair, table, shelf, lamp post). False for
small or handheld objects, objects lying flat, and objects shown mainly from above.
served_food: true only when the main object is real food or a dish of food (fruit, vegetables, bread, cake, a meal on a
plate, a drink in a glass). False for toys, figurines, packaging, empty containers and pictures of food."""

PROMPT = "Classify the main object in this photo."


def schema() -> dict:
    return {
        "format": {
            "type": "json_schema",
            "name": "object_route",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "upright_structure", "served_food"],
                "properties": {"category": {"type": "string", "enum": list(CATEGORIES)},
                               "upright_structure": {"type": "boolean"},
                               "served_food": {"type": "boolean"}},
            },
        }
    }


@dataclass(frozen=True)
class Route:
    category: str = ""
    upright: bool = False
    food: bool = False


NONE = Route()


def parse(text: str | None) -> Route:
    """The levers from the reply; NONE when it is missing or does not follow the schema."""
    try:
        reply = json.loads(text or "")
        category = reply["category"]
        if category not in CATEGORIES:
            return NONE
        return Route(category,
                     upright=category in UPRIGHT_CATEGORIES and reply["upright_structure"] is True,
                     food=category == "food" and reply["served_food"] is True)
    except (TypeError, KeyError, ValueError, AttributeError):
        return NONE
