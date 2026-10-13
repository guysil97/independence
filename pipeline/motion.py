"""Per-plane camera tracking: homography ref -> every frame of the working range.

Chained frame-to-frame KLT gives the initial guess; each frame is then
re-registered directly against the reference frame (KLT seeded with the chained
prediction) so there is no accumulated drift.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import regions as rg


def _plane_mask(regions: dict, plane: str, shape, grow=60) -> np.ndarray:
    spec = regions.get("planes", {}).get(plane, {})
    m = np.zeros(shape, np.uint8)
    if "track_poly" in spec:
        m = (rg.hard_mask(spec["track_poly"], shape) > 0.5).astype(np.uint8)
    else:
        for group in ("windows", "foreground"):
            for reg in regions[group].values():
                if reg["plane"] == plane:
                    m = np.maximum(m, (rg.hard_mask(reg["poly"], shape) > 0.5).astype(np.uint8))
        m = cv2.dilate(m, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
    if "actor_rough" in regions:
        a = (rg.hard_mask(regions["actor_rough"]["poly"], shape) > 0).astype(np.uint8)
        m[a > 0] = 0
    return m * 255


def _fit(src, dst, ransac_px, model="homography"):
    if len(src) < 12:
        return None, 0
    if model == "affine":
        A, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=ransac_px)
        return (None, 0) if A is None else (np.vstack([A, [0, 0, 1]]), int(inl.sum()))
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, ransac_px, maxIters=5000, confidence=0.999)
    if H is None or inl.sum() < 12:
        A, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=ransac_px)
        if A is None:
            return None, 0
        H = np.vstack([A, [0, 0, 1]])
    return H, int(inl.sum())


def _ecc(ref_g, cur_g, mask, H0, scales=(0.25, 0.5), model="homography"):
    """Masked ECC homography ref->cur, coarse to fine. Returns (H, correlation)."""
    H = H0.astype(np.float32).copy()
    cc = -1.0
    for s in scales:
        S = np.diag([s, s, 1]).astype(np.float32)
        a = cv2.resize(ref_g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA).astype(np.float32)
        b = cv2.resize(cur_g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA).astype(np.float32)
        m = cv2.resize(mask, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST)
        Hs = S @ H @ np.linalg.inv(S)
        mt = cv2.MOTION_HOMOGRAPHY if model == "homography" else cv2.MOTION_AFFINE
        try:
            cc, Hs = cv2.findTransformECC(a, b, (Hs if model == "homography" else Hs[:2]).astype(np.float32), mt,
                                          (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6),
                                          m, 5)
        except cv2.error:
            return None, -1.0
        if Hs.shape[0] == 2:
            Hs = np.vstack([Hs, [0, 0, 1]]).astype(np.float32)
        H = np.linalg.inv(S) @ Hs @ S
    return (H / H[2, 2]).astype(np.float64), float(cc)


def track(grays: list[np.ndarray], regions: dict, ref: int, params: dict, actor_masks=None) -> dict:
    """grays: uint8 frames. actor_masks: optional per-frame bool masks of the actors (from
    the protection mattes) excluded from tracking. Returns {plane: {"H": [N,3,3], ...}}."""
    no_actor = (lambda m, i: m) if actor_masks is None else (lambda m, i: m * (~actor_masks[i]).astype(np.uint8))
    shape = grays[0].shape
    lk = dict(winSize=(31, 31), maxLevel=5,
              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01))
    planes = sorted({r["plane"] for g in ("windows", "foreground") for r in regions[g].values()})
    out = {}
    for plane in planes:
        model = regions.get("planes", {}).get(plane, {}).get("model", "homography")
        mask = _plane_mask(regions, plane, shape)
        mask_ref = no_actor(mask, ref)
        p_ref = cv2.goodFeaturesToTrack(grays[ref], params["max_corners"], params["quality"],
                                        params["min_distance"], mask=mask_ref, blockSize=7)
        if p_ref is None:
            p_ref = np.zeros((0, 1, 2), np.float32)
        N = len(grays)
        Hs = [None] * N
        inl = [0] * N
        Hs[ref] = np.eye(3)
        inl[ref] = len(p_ref)
        ecc = [1.0] * N
        for direction in (1, -1):
            t = ref + direction
            while 0 <= t < N:
                prev = t - direction
                p0 = cv2.goodFeaturesToTrack(grays[prev], params["max_corners"], params["quality"],
                                             params["min_distance"], mask=no_actor(mask, prev), blockSize=7)
                p1, st, _ = cv2.calcOpticalFlowPyrLK(grays[prev], grays[t], p0, None, **lk)
                pb, stb, _ = cv2.calcOpticalFlowPyrLK(grays[t], grays[prev], p1, None, **lk)
                ok = (st[:, 0] == 1) & (stb[:, 0] == 1) & (np.linalg.norm(pb - p0, axis=2)[:, 0] < 0.5)
                Hstep, _ = _fit(p0[ok], p1[ok], params["ransac_px"], model)
                Hguess = (Hstep if Hstep is not None else np.eye(3)) @ Hs[prev]
                # direct re-registration against the reference
                guess = cv2.perspectiveTransform(p_ref, Hguess).astype(np.float32)
                p1r, st, _ = cv2.calcOpticalFlowPyrLK(grays[ref], grays[t], p_ref, guess.copy(),
                                                      flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **lk)
                pbr, stb, _ = cv2.calcOpticalFlowPyrLK(grays[t], grays[ref], p1r, p_ref.copy(),
                                                       flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **lk)
                ok = (st[:, 0] == 1) & (stb[:, 0] == 1) & (np.linalg.norm(pbr - p_ref, axis=2)[:, 0] < 0.5)
                Hd, n = _fit(p_ref[ok], p1r[ok], params["ransac_px"], model)
                if Hd is None or n < 30:
                    Hd = Hguess
                # dense ECC refinement: robust on defocused, low-texture planes
                He, cc = _ecc(grays[ref], grays[t], mask_ref, Hd, model=model)
                if He is not None and cc >= params.get("ecc_min_cc", 0.85):
                    Hs[t], inl[t], ecc[t] = He, n, cc
                else:
                    Hs[t], inl[t], ecc[t] = Hd, -n, cc  # negative = no dense confirmation
                t += direction
        H_all, repaired = repair_spikes(np.stack(Hs), shape, params.get("spike_px", 2.0))
        out[plane] = {"H": H_all, "repaired_frames": repaired, "inliers": np.array(inl), "ecc_cc": np.array(ecc), "n_ref": int(len(p_ref))}
    return out


def repair_spikes(H, shape, thresh_px=2.0, win=7):
    """Camera paths are smooth: replace frames whose frame corners jump off a
    running median by > thresh_px with an interpolation of their neighbours."""
    from scipy.ndimage import median_filter

    h, w = shape
    c = np.float64([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]])
    traj = np.stack([cv2.perspectiveTransform(c, Hi).reshape(-1) for Hi in H])  # N x 8
    med = median_filter(traj, size=(win, 1), mode="nearest")
    bad = np.abs(traj - med).max(1) > thresh_px
    if not bad.any() or bad.all():
        return H, []
    good = np.where(~bad)[0]
    fixed = traj.copy()
    for j in range(8):
        fixed[bad, j] = np.interp(np.where(bad)[0], good, traj[good, j])
    H = H.copy()
    for i in np.where(bad)[0]:
        H[i] = cv2.getPerspectiveTransform(c.reshape(4, 2).astype(np.float32),
                                           fixed[i].reshape(4, 2).astype(np.float32))
    return H, [int(i) for i in np.where(bad)[0]]


def displacement(H: np.ndarray, poly) -> np.ndarray:
    """Max displacement (px) of the polygon's vertices under each H vs. identity."""
    pts = np.asarray(poly, np.float64).reshape(-1, 1, 2)
    return np.array([np.linalg.norm(cv2.perspectiveTransform(pts, h) - pts, axis=2).max() for h in H])
