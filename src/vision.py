"""CPU-only vision (no model calls): object masks, photo measurements for the measured fallback, render checks."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageFilter

Mask = npt.NDArray[np.bool_]
SIDE = 192  # side of the normalised masks used to compare shapes


def photo_mask(photo: Image.Image, side: int = 512) -> Mask:
    """Object mask of the prompt photo; the background colour is estimated from the image border."""
    im = photo.convert("RGB")
    sc = side / max(im.size)
    im = im.resize((max(1, round(im.width * sc)), max(1, round(im.height * sc))), Image.Resampling.BILINEAR)
    x = np.asarray(im).astype(np.float32)
    border = np.concatenate(
        [x[:6].reshape(-1, 3), x[-6:].reshape(-1, 3), x[:, :6].reshape(-1, 3), x[:, -6:].reshape(-1, 3)]
    )
    bg = np.median(border, axis=0)
    tol = max(18.0, 3.0 * float(np.median(np.abs(border - bg).sum(1))))
    m = Image.fromarray(((np.abs(x - bg).sum(2) > tol) * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))
    return np.asarray(m) > 127


def render_mask(im: Image.Image) -> Mask:
    return np.asarray(im.convert("L")) < 245


def crop_box(m: Mask) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(m)
    if len(ys) < 20:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def norm(m: Mask, side: int = SIDE) -> Mask | None:
    """Crop to the object box and centre it in a square, so shapes compare regardless of size and position."""
    b = crop_box(m)
    if b is None:
        return None
    c = m[b[1] : b[3], b[0] : b[2]]
    h, w = c.shape
    s = max(h, w)
    sq = np.zeros((s, s), bool)
    sq[(s - h) // 2 : (s - h) // 2 + h, (s - w) // 2 : (s - w) // 2 + w] = c
    return np.asarray(Image.fromarray(sq.astype(np.uint8) * 255).resize((side, side), Image.Resampling.NEAREST)) > 127


def iou(a: Mask | None, b: Mask | None) -> float:
    if a is None or b is None:
        return 0.0
    return float((a & b).sum() / max(1, (a | b).sum()))


def _profile(m: Mask, rows: int = 10) -> list[float]:
    b = crop_box(m)
    if b is None:
        return []
    c = m[b[1] : b[3], b[0] : b[2]]
    widths = [int(c[min(c.shape[0] - 1, int((i + 0.5) * c.shape[0] / rows))].sum()) for i in range(rows)]
    top = max(widths) or 1
    return [round(w / top, 2) for w in widths]


def _object_pixels(im: Image.Image, m: Mask) -> npt.NDArray[np.float32]:
    a = np.asarray(im.convert("RGB").resize((m.shape[1], m.shape[0]), Image.Resampling.BILINEAR)).astype(np.float32)
    pixels: npt.NDArray[np.float32] = a[m]
    return pixels


def _stats(im: Image.Image, m: Mask) -> dict[str, Any]:
    px = _object_pixels(im, m)
    b = crop_box(m)
    if len(px) == 0 or b is None:
        return {}
    mx, mn = px.max(1), px.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    grey = np.asarray(im.convert("L").resize((m.shape[1], m.shape[0]))).astype(np.float32)
    gy, gx = np.gradient(grey)
    edges = float(np.hypot(gx, gy)[m].mean())
    return {
        "h_over_w": round((b[3] - b[1]) / max(1, b[2] - b[0]), 2),
        "profile": _profile(m),
        "median_rgb": [int(v) for v in np.median(px, 0)],
        "brightness": round(float(px.mean()) / 255, 2),
        "highlights": round(float(((mx > 235) & (sat < 0.12)).mean()), 3),
        "edge_density": round(edges / 255, 3),
    }


def measure_photo(photo: Image.Image) -> dict[str, Any]:
    m = photo_mask(photo)
    s = _stats(photo.resize((m.shape[1], m.shape[0])), m)
    return {
        "height_over_width": s.get("h_over_w"),
        "width_profile_top_to_bottom": s.get("profile"),
        "median_colour_rgb": s.get("median_rgb"),
        "brightness_0_1": s.get("brightness"),
    }


def best_view(photo: Image.Image, views: dict[str, Image.Image]) -> tuple[str, float]:
    """The render view whose silhouette is closest to the photo; only picks the image shown to the critic."""
    pm = norm(photo_mask(photo))
    scored = sorted(((iou(pm, norm(render_mask(im))), k) for k, im in views.items()), reverse=True)
    return scored[0][1], scored[0][0]


def checks(front: dict[str, Image.Image], around: dict[str, Image.Image] | None) -> list[str]:
    """Deterministic checks on the renders (img2threejs turntable-gate style)."""
    issues = []
    areas = {k: float(render_mask(im).mean()) for k, im in front.items()}
    if max(areas.values(), default=0) < 0.002:
        return ["EMPTY: nothing visible from the judge cameras (NaN geometry or zero scale)"]
    pieces = _components(render_mask(front["front_left"]))
    if pieces > 1:
        issues.append(f"{pieces} separate pieces visible from front-left — check for floating parts")
    if around:
        ref = max(areas.values())
        for k in ("right", "left", "back"):
            if k in around and float(render_mask(around[k]).mean()) < 0.12 * ref:
                issues.append(f"very thin seen from the {k} — may look paper-thin to the judge")
    return issues


def _components(m: Mask, side: int = 96, min_frac: float = 0.01) -> int:
    """Count connected pieces holding ≥1% of the object area (4-neighbour labelling on a downscaled mask)."""
    s = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((side, side), Image.Resampling.NEAREST)) > 127
    seen = np.zeros_like(s)
    sizes = []
    for y, x in zip(*np.nonzero(s)):
        if seen[y, x]:
            continue
        stack = [(int(y), int(x))]
        seen[y, x] = True
        n = 0
        while stack:
            cy, cx = stack.pop()
            n += 1
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < side and 0 <= nx < side and s[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        sizes.append(n)
    total = max(1, sum(sizes))
    return sum(1 for n in sizes if n >= min_frac * total)


def object_closeup(photo: Image.Image, side: int = 1024) -> Image.Image | None:
    """The object cropped from the photo with a small margin, long side `side` px; None when the object already
    fills most of the photo or no object is found (the close-up would add nothing)."""
    m = photo_mask(photo)
    b = crop_box(m)
    if b is None:
        return None
    sx, sy = photo.width / m.shape[1], photo.height / m.shape[0]
    pad = 0.06 * max(b[2] - b[0], b[3] - b[1])
    x0, y0 = max(0.0, (b[0] - pad) * sx), max(0.0, (b[1] - pad) * sy)
    x1, y1 = min(float(photo.width), (b[2] + pad) * sx), min(float(photo.height), (b[3] + pad) * sy)
    if (x1 - x0) * (y1 - y0) > 0.5 * photo.width * photo.height:
        return None
    crop = photo.convert("RGB").crop((round(x0), round(y0), round(x1), round(y1)))
    sc = side / max(crop.size)
    return crop.resize((max(1, round(crop.width * sc)), max(1, round(crop.height * sc))), Image.Resampling.LANCZOS)


# ---- colour layout: does a render show the photo's colours in the same places? (pose candidates) ----------------
_N, _K = 96, 6


def _lab(rgb: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    a = rgb / 255.0
    a = np.where(a > 0.04045, ((a + 0.055) / 1.055) ** 2.4, a / 12.92)
    xyz = a @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz = xyz / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _square(im: Image.Image, m: Mask) -> tuple[npt.NDArray[np.float64], Mask] | None:
    """Object crop centred in a square, _N px: (Lab pixels, mask)."""
    b = crop_box(m)
    if b is None:
        return None
    rgb = im.convert("RGB").resize((m.shape[1], m.shape[0]), Image.Resampling.BILINEAR)
    s = max(b[2] - b[0], b[3] - b[1])
    cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
    box = (cx - s // 2, cy - s // 2, cx - s // 2 + s, cy - s // 2 + s)
    lab = _lab(np.asarray(rgb.crop(box).resize((_N, _N), Image.Resampling.BOX)).astype(np.float64))
    mm = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).crop(box).resize((_N, _N), Image.Resampling.BOX)) > 127
    return lab, mm


def _grow(m: Mask, r: int) -> Mask:
    p = np.pad(m, r)
    out = np.zeros_like(m)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= p[dy : dy + m.shape[0], dx : dx + m.shape[1]]
    return out


def _edges(lb: npt.NDArray[np.int64]) -> Mask:
    e = np.zeros(lb.shape, bool)
    e[1:] |= lb[1:] != lb[:-1]
    e[:, 1:] |= lb[:, 1:] != lb[:, :-1]
    return e


class ColourLayout:
    """The photo's main colours (k-means in Lab) and where their borders run. score(views) = the worst view's
    agreement (F-score, 2 px tolerance) between the borders of the render's colour regions and the photo's. Checked
    on 549 judged rotations of round-1 modules: tilts towards the camera that raise it by more than 0.02 won more
    duels than they lost; plain turns did not, so only tilts use it."""

    def __init__(self, photo: Image.Image) -> None:
        sq = _square(photo, photo_mask(photo))
        self.ok = sq is not None
        if sq is None:
            return
        lab, mask = sq
        px = lab[mask]
        self.mu, self.sd = float(px[:, 0].mean()), float(px[:, 0].std()) + 1e-6
        c = np.quantile(px, np.linspace(0.05, 0.95, _K), axis=0)
        for _ in range(15):  # fixed iterations from fixed starts: the same centres on every run
            lb = np.argmin(((px[:, None] - c[None]) ** 2).sum(-1), 1)
            c = np.stack([px[lb == j].mean(0) if (lb == j).any() else c[j] for j in range(_K)])
        self.c = c
        self.edges = _edges(self._labels(lab, mask))

    def _labels(self, lab: npt.NDArray[np.float64], mask: Mask) -> npt.NDArray[np.int64]:
        lb = np.argmin(((lab[..., None, :] - self.c) ** 2).sum(-1), -1)
        return np.where(mask, lb, -1)

    def view(self, im: Image.Image) -> float:
        sq = _square(im, render_mask(im))
        if sq is None:
            return 0.0
        lab, mask = sq
        if mask.any():  # the renderer's light is not the photo's: match the object's brightness spread first
            L = lab[..., 0]
            lab = lab.copy()
            lab[..., 0] = (L - L[mask].mean()) / (L[mask].std() + 1e-6) * self.sd + self.mu
        e = _edges(self._labels(lab, mask))
        prec = (e & _grow(self.edges, 2)).sum() / max(1, e.sum())
        rec = (self.edges & _grow(e, 2)).sum() / max(1, self.edges.sum())
        return float(2 * prec * rec / max(1e-6, prec + rec))

    def score(self, views: dict[str, Image.Image]) -> float:
        return min(self.view(im) for im in views.values()) if self.ok else 0.0

