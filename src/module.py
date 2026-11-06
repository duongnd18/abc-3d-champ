"""Assemble the submitted module: helper library + the model's build(THREE) + framing.

The model writes only `function build(THREE) { ... return group; }` (and its own helpers). The helper library is
prepended; the framing code (prompts/frame.js) turns the object to the chosen pose, tips it towards the camera when
flat objects by 15° (the model tilts other objects itself, playbook item 2), applies the judge's material rules, bakes
every part's transform into its geometry and fits the tight box to the 0.99 cube, so every module has the same frame
and satisfies the output rules.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HELPERS = (Path(__file__).with_name("prompts") / "helpers.js").read_text()
FRAME = (Path(__file__).with_name("prompts") / "frame.js").read_text()
_FENCE = re.compile(r"```(?:javascript|js|mjs)?[ \t]*\n(.*?)```", re.DOTALL)
_EXPORT = re.compile(r"export\s+default\s+")
# The checker rejects these names anywhere, even as the model's own variables (`window` of a cabinet, `self`).
# Renaming every occurrence consistently cannot break a module the checker would accept, and saves a repair call.
FORBIDDEN = (
    "eval",
    "Function",
    "setTimeout",
    "setInterval",
    "setImmediate",
    "queueMicrotask",
    "fetch",
    "XMLHttpRequest",
    "WebSocket",
    "document",
    "window",
    "navigator",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "OffscreenCanvas",
    "HTMLCanvasElement",
    "crypto",
    "Date",
    "performance",
    "Proxy",
    "Reflect",
    "WeakRef",
    "FinalizationRegistry",
    "SharedArrayBuffer",
    "Atomics",
    "Worker",
    "process",
    "module",
    "global",
    "globalThis",
    "self",
    "require",
)
_FORBIDDEN = re.compile(r"(?<![\w$])(" + "|".join(FORBIDDEN) + r")(?![\w$])")
LIBRARY_FUNCS = (
    "lathe",
    "hollowLathe",
    "roundRectShape",
    "roundedBox",
    "extrudeOutline",
    "tube",
    "mat",
    "patternTexture",
    "ringOf",
    "place",
    "tiltTowardCamera",
    "capVertices",
    "fitToUnitCube",
)


@dataclass(frozen=True)
class Pose:
    """Whole-object rotation: yaw about Y, then pitch about X (degrees).

    A flat object is then tipped 15° towards the camera.
    """

    yaw: int = 0
    pitch: int = 0
    cap: bool = False  # drop the costliest parts to fit the vertex limit (last resort, see frame.js capVertices)
    tilt: int = 0  # extra tilt towards the camera after the flat-object tilt (degrees; pose candidates)


UPRIGHT = Pose()


def extract_build(text: str) -> str | None:
    """Return the build(THREE) code from a reply, without exports or copies of library functions."""
    blocks = _FENCE.findall(text) or [text]
    code = max((b for b in blocks if "function build" in b), key=len, default=None)
    if code is None:
        return None
    code = _EXPORT.sub("", code)
    for name in LIBRARY_FUNCS:  # a top-level function named like a library one would be declared twice
        code = _rename_own(code, name)
    return code.strip() + "\n"


def _rename_own(code: str, name: str) -> str:
    """The model declared its own top-level `name` (a copy, or its own helper with other parameters): rename it and
    every reference in the model's code, so its calls keep reaching its own version and the library stays intact.
    (Dropping the model's version instead sent its calls to the library one, with the wrong arguments.)"""
    if not re.search(rf"^function\s+{name}\s*\(", code, re.MULTILINE):
        return code

    def swap(m: re.Match[str]) -> str:
        before, after = code[: m.start()].rstrip(), code[m.end() :].lstrip()
        if before.endswith(("{", ",")) and after.startswith(":"):  # an object key such as { mat: … }
            return m.group(0)
        return f"{name}_own"

    return re.sub(rf"(?<![\w$.]){name}(?![\w$])", swap, code)


def assemble(build: str, pose: Pose = UPRIGHT) -> str:
    return (
        HELPERS + "\n" + _FORBIDDEN.sub(r"\1_", build.rstrip()) + "\n\n" + FRAME + "\n"
        "export default function generate(THREE) {\n"
        "  const model = build(THREE);\n"
        f"  const yawG = new THREE.Group(); yawG.add(model); yawG.rotation.y = {math.radians(pose.yaw):.6f};\n"
        f"  const pitchG = new THREE.Group(); pitchG.add(yawG); pitchG.rotation.x = {math.radians(pose.pitch):.6f};\n"
        "  const tiltG = new THREE.Group(); tiltG.add(pitchG);\n"
        "  tiltTowardCamera(THREE, tiltG);\n"
        + (f"  tiltG.rotation.x += {math.radians(pose.tilt):.6f};\n" if pose.tilt else "")
        + "  const root = new THREE.Group(); root.add(tiltG);\n"
        + ("  capVertices(THREE, root);\n" if pose.cap else "")
        + "  __gen3dMergeDraws(THREE, root);\n"
        "  __gen3dTextureBudget(THREE, root);\n"
        "  __bake(THREE, root);\n"
        "  fitToUnitCube(THREE, root);\n"
        "  return root;\n"
        "}\n"
    )


_FALLBACK = """function build(THREE) {
  // No model output rendered: the photo's measured outline revolved, in its median colour.
  const radii = [RADII];
  const h = HEIGHT;
  const pts = [new THREE.Vector2(0, 0)];
  radii.forEach((r, i) => pts.push(new THREE.Vector2(r, ((i + 0.5) / radii.length) * h)));
  pts.push(new THREE.Vector2(0, h));
  const g = new THREE.Group();
  g.add(new THREE.Mesh(new THREE.LatheGeometry(pts, 48), new THREE.MeshStandardMaterial({ color: COLOR, roughness: 0.6 })));
  return g;
}
"""


def fallback_build(meas: dict[str, Any]) -> str:
    """build(THREE) made without any model call, from vision.measure_photo: width profile, aspect and colour."""
    widths = [float(w) for w in meas.get("width_profile_top_to_bottom") or []] or [1.0] * 10
    height = min(4.0, max(0.25, float(meas.get("height_over_width") or 1.0)))
    rgb = [int(c) for c in (meas.get("median_colour_rgb") or [150, 150, 150])[:3]]
    radii = ", ".join(f"{max(0.04, min(1.0, w)) / 2:.3f}" for w in reversed(widths))  # bottom → top
    colour = "0x" + "".join(f"{c:02x}" for c in rgb)
    return _FALLBACK.replace("RADII", radii).replace("HEIGHT", f"{height:.3f}").replace("COLOR", colour)
