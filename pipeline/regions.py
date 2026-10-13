"""Region polygons -> soft masks, tracked through per-plane homographies."""
from __future__ import annotations

import json

import cv2
import numpy as np


def load(cfg: dict) -> dict:
    r = json.loads(cfg["_regions_path"].read_text())
    for group in ("windows", "foreground"):
        r[group] = {k: v for k, v in r.get(group, {}).items() if not k.startswith("_")}
    return r


def _warp_poly(poly, H):
    pts = np.asarray(poly, dtype=np.float64).reshape(-1, 1, 2)
    if H is not None:
        pts = cv2.perspectiveTransform(pts, H)
    return pts.reshape(-1, 2)


def hard_mask(poly, shape, H=None, ss=4) -> np.ndarray:
    """Anti-aliased polygon coverage in [0,1] (float32)."""
    h, w = shape
    pts = np.round(_warp_poly(poly, H) * ss).astype(np.int32)
    m = np.zeros((h * ss, w * ss), np.uint8)
    cv2.fillPoly(m, [pts], 255)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def soft(mask: np.ndarray, feather: float) -> np.ndarray:
    """Feather symmetrically around the polygon edge (sigma = feather/2)."""
    if feather <= 0:
        return mask
    return cv2.GaussianBlur(mask, (0, 0), feather / 2.0)


def region_mask(reg: dict, shape, H=None) -> np.ndarray:
    return soft(hard_mask(reg["poly"], shape, H), reg.get("feather", 0))


def frame_masks(regions: dict, shape, Hs: dict | None = None) -> dict:
    """All window masks with their plane's foreground objects removed, for one frame.

    Hs: plane name -> 3x3 homography ref->frame (None = identity).
    Returns {"<window>": mask, "fg_<name>": mask, "windows_all": union}.
    """
    Hs = Hs or {}
    out = {}
    fg_by_plane: dict[str, np.ndarray] = {}
    for name, reg in regions["foreground"].items():
        m = region_mask(reg, shape, Hs.get(reg["plane"]))
        out[f"fg_{name}"] = m
        p = reg["plane"]
        fg_by_plane[p] = np.maximum(fg_by_plane.get(p, 0), m)
    union = np.zeros(shape, np.float32)
    for name, reg in regions["windows"].items():
        m = region_mask(reg, shape, Hs.get(reg["plane"]))
        if reg["plane"] in fg_by_plane:
            m = m * (1.0 - fg_by_plane[reg["plane"]])
        out[name] = m
        union = np.maximum(union, m)
    out["windows_all"] = union
    return out


def draw_overlay(img_rgb8: np.ndarray, regions: dict, Hs: dict | None = None, labels=True) -> np.ndarray:
    Hs = Hs or {}
    im = img_rgb8.copy()
    colors = {"blinds_A": (255, 170, 0), "blinds_B": (0, 220, 255), "door_glass": (80, 255, 80),
              "frosted_panels": (190, 120, 255)}
    tint = im.astype(np.float32)
    for name, reg in regions["windows"].items():
        c = colors.get(name, (255, 255, 0))
        m = region_mask(reg, im.shape[:2], Hs.get(reg["plane"]))[..., None]
        tint = tint * (1 - 0.28 * m) + np.array(c, np.float32) * 0.28 * m
    for reg in regions["foreground"].values():
        m = region_mask(reg, im.shape[:2], Hs.get(reg["plane"]))[..., None]
        tint = tint * (1 - 0.45 * m) + np.array((255, 0, 60), np.float32) * 0.45 * m
    im = np.clip(tint, 0, 255).astype(np.uint8)
    for group, col in (("windows", None), ("foreground", (255, 40, 90))):
        for name, reg in regions[group].items():
            c = col or colors.get(name, (255, 255, 0))
            pts = np.round(_warp_poly(reg["poly"], Hs.get(reg["plane"]))).astype(np.int32)
            cv2.polylines(im, [pts], True, c, 2, cv2.LINE_AA)
            if labels:
                x, y = pts.min(0)
                yy = int(y) + 26 if group == "windows" else int(y) - 8
                cv2.putText(im, name, (int(x) + 6, max(yy, 18) + (40 if name == "door_edge_frame" else 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2, cv2.LINE_AA)
    return im
