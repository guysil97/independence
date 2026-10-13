"""Step 1.4–1.7: regions, camera motion and plate characterisation -> CHECKPOINT 1.

    python -m pipeline.analyze shot01
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile

from . import colorpipe, config, motion
from . import regions as rg


def load_frames(cfg):
    fr = sorted(Path(config.work(cfg, "frames")).glob("*.tif"))
    return [tifffile.imread(f).astype(np.float32) / 65535.0 for f in fr]


def to8(img):
    return np.clip(np.rint(img * 255), 0, 255).astype(np.uint8)


def detect_cuts(grays, thresh=0.3):
    """Frame-to-frame phase-correlation response; a collapse means an edit point."""
    cuts, resp = [], []
    for i in range(1, len(grays)):
        a = cv2.resize(grays[i - 1], None, fx=.25, fy=.25).astype(np.float32)
        b = cv2.resize(grays[i], None, fx=.25, fy=.25).astype(np.float32)
        a, b = cv2.GaussianBlur(a, (0, 0), 2), cv2.GaussianBlur(b, (0, 0), 2)
        _, r = cv2.phaseCorrelate(a, b)
        resp.append(r)
        if r < thresh:
            cuts.append(i)
    return cuts, resp


# --------------------------------------------------------------------------- blinds
def blinds_analysis(Y, mask, actor, period_guess=(4, 40)):
    """Slat period/orientation and gap vs. slat luminance from linear luminance Y."""
    valid = (mask > 0.98) & (actor < 0.5)
    ys, xs = np.where(valid)
    if len(ys) < 500:
        return None
    hp = Y - cv2.GaussianBlur(Y, (0, 0), 12)
    # row profile (orientation is near-horizontal; refined below)
    rows = np.arange(ys.min(), ys.max() + 1)
    prof = np.array([hp[r, valid[r]].mean() if valid[r].any() else 0 for r in rows])
    prof = prof - prof.mean()
    n = 1 << int(np.ceil(np.log2(len(prof) * 4)))
    spec = np.abs(np.fft.rfft(prof * np.hanning(len(prof)), n))
    freqs = np.fft.rfftfreq(n)
    band = (freqs > 1 / period_guess[1]) & (freqs < 1 / period_guess[0])
    period = 1.0 / freqs[band][np.argmax(spec[band])]
    # orientation: structure tensor over valid pixels
    gx = cv2.Sobel(hp, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(hp, cv2.CV_32F, 0, 1, ksize=5)
    jxx, jyy, jxy = (gx * gx)[valid].sum(), (gy * gy)[valid].sum(), (gx * gy)[valid].sum()
    grad_angle = 0.5 * np.degrees(np.arctan2(2 * jxy, jxx - jyy))  # dominant gradient direction
    slat_angle = grad_angle - 90.0 if grad_angle > 0 else grad_angle + 90.0  # slat line direction
    coherence = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-12)
    # gaps vs slats: local max/min over one period vertically
    k = int(round(period * 1.2)) | 1
    lmax = cv2.dilate(Y, np.ones((k, 3), np.uint8))
    lmin = cv2.erode(Y, np.ones((k, 3), np.uint8))
    gap = lmax[valid]
    slat = lmin[valid]
    return {
        "slat_period_px": float(period), "slat_angle_deg": float(slat_angle), "orientation_coherence": float(coherence),
        "gap_lum_lin_median": float(np.median(gap)), "slat_lum_lin_median": float(np.median(slat)),
        "slat_to_gap_ratio": float(np.median(slat / np.maximum(gap, 1e-6))),
        "valid_px": int(valid.sum()),
    }


def transmission_map(Y, win_masks, fg_union, period):
    """Per-pixel transmission in [0,1]: bright gaps ~1, slat faces lower, frames/opaque -> 0."""
    k = int(round(period * 1.5)) | 1
    lmax = cv2.dilate(Y, np.ones((k, 5), np.uint8))
    lmax = cv2.GaussianBlur(lmax, (0, 0), period)
    T = np.clip(Y / np.maximum(lmax, 1e-6), 0, 1)
    # opaque structure (frames, cords): much darker than the regional backlight -> 0
    regional = cv2.GaussianBlur(lmax, (0, 0), 25)
    T *= np.clip((lmax / np.maximum(regional, 1e-6) - 0.25) / 0.35, 0, 1)
    return (T * win_masks * (1 - fg_union)).astype(np.float32)


# --------------------------------------------------------------------------- bokeh
def measure_bokeh(Y, cx, cy, half=70):
    h, w = Y.shape
    x0, y0 = max(0, cx - half), max(0, cy - half)
    crop = Y[y0:min(h, cy + half), x0:min(w, cx + half)]
    bg, pk = np.percentile(crop, 10), np.percentile(crop, 99.5)
    m = (crop > bg + 0.5 * (pk - bg)).astype(np.uint8)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    d = [np.hypot(*(cent[i] - (cx - x0, cy - y0))) for i in range(1, n)]
    i = 1 + int(np.argmin(d))
    blob = lab == i
    yy, xx = np.nonzero(blob)
    mx, my = xx.mean(), yy.mean()
    cov = np.cov(np.stack([xx - mx, yy - my]))
    ev, evec = np.linalg.eigh(cov)
    major, minor = 4 * np.sqrt(ev[1]), 4 * np.sqrt(ev[0])  # uniform ellipse: var = a^2/4
    ang = np.degrees(np.arctan2(evec[1, 1], evec[0, 1]))
    touches = (yy.min() == 0) or (xx.min() == 0) or (yy.max() == crop.shape[0] - 1) or (xx.max() == crop.shape[1] - 1)

    def edge_width(direction):
        dx, dy = direction
        rs = np.linspace(0, 0.9 * half, 200)
        px, py = mx + rs * dx, my + rs * dy
        v = cv2.remap(crop.astype(np.float32), px.astype(np.float32)[None], py.astype(np.float32)[None],
                      cv2.INTER_LINEAR)[0]
        v = (v - bg) / max(pk - bg, 1e-9)
        try:
            r90 = rs[np.where(v < 0.9)[0][0]]
            r10 = rs[np.where(v < 0.1)[0][0]]
            return float(r10 - r90)
        except IndexError:
            return None

    widths = [edge_width((np.cos(t), np.sin(t))) for t in np.linspace(0, 2 * np.pi, 16, endpoint=False)]
    widths = [w_ for w_ in widths if w_ is not None]
    inner = crop[blob]
    erode = cv2.erode(blob.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    core = crop[erode] if erode.any() else inner
    ring = crop[blob & ~erode]
    return {
        "center": [float(mx + x0), float(my + y0)], "major_px": float(major), "minor_px": float(minor),
        "aspect_v_over_h": float(np.sqrt(cov[1, 1] / cov[0, 0])), "major_axis_angle_deg": float(ang),
        "edge_10_90_px": float(np.median(widths)) if widths else None,
        "interior_cv": float(core.std() / max(core.mean(), 1e-9)),
        "rim_to_core_ratio": float(ring.mean() / max(core.mean(), 1e-9)) if ring.size else None,
        "peak_lin": float(pk), "bg_lin": float(bg), "clipped_by_crop_edge": bool(touches),
        "_crop": (x0, y0, crop, blob),
    }


def find_bokeh(Y, excl, min_area=150, max_area=9000):
    """Isolated, convex, bright defocus discs (interior practicals) -> candidate centres."""
    bg = cv2.morphologyEx(Y, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (121, 121)))
    bg = cv2.GaussianBlur(bg, (0, 0), 15)
    D = Y - bg
    thr = max(0.02, np.percentile(D, 99) * 0.5)
    m = ((D > thr) & ~excl).astype(np.uint8)
    n, lab, st, cent = cv2.connectedComponentsWithStats(m)
    h, w = Y.shape
    out = []
    for i in range(1, n):
        x, y, bw, bh, a = st[i]
        if not (min_area <= a <= max_area) or x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2:
            continue
        cnt, _ = cv2.findContours((lab[y:y + bh, x:x + bw] == i).astype(np.uint8), cv2.RETR_EXTERNAL,
                                  cv2.CHAIN_APPROX_NONE)
        hull = cv2.contourArea(cv2.convexHull(cnt[0]))
        if hull <= 0 or a / hull < 0.93:
            continue
        peak = Y[lab == i].max()
        out.append((float(peak / max(bg[int(cent[i][1]), int(cent[i][0])], 1e-4)), int(cent[i][0]), int(cent[i][1]),
                    int(max(bw, bh))))
    return sorted(out, reverse=True)


# --------------------------------------------------------------------------- noise
def noise_analysis(code, excl, patch=32):
    """Find the flattest dark and bright patches; per-channel noise std (code values) + correlation."""
    Yc = code @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    h, w = Yc.shape
    cands = []
    for y in range(0, h - patch, patch // 2):
        for x in range(0, w - patch, patch // 2):
            if excl[y:y + patch, x:x + patch].any():
                continue
            p = Yc[y:y + patch, x:x + patch]
            hp = p - cv2.GaussianBlur(p, (0, 0), 3)
            sm = cv2.GaussianBlur(p, (0, 0), 3)
            grad = abs(sm[0].mean() - sm[-1].mean()) + abs(sm[:, 0].mean() - sm[:, -1].mean())
            cands.append((p.mean(), hp.std() + grad, x, y))
    cands = np.array(cands)
    res = {}
    for name, lo, hi in (("dark", 0.02, 0.18),):  # no flat bright area exists outside the windows
        sel = cands[(cands[:, 0] > lo) & (cands[:, 0] < hi)]
        if not len(sel):
            continue
        best = sel[np.argsort(sel[:, 1])[:6]]
        stds, corr = [], []
        for _, _, x, y in best:
            x, y = int(x), int(y)
            p = code[y:y + patch, x:x + patch]
            r = p - cv2.GaussianBlur(p, (0, 0), 3)
            stds.append(r.reshape(-1, 3).std(0))
            rl = r.mean(2)
            c1 = np.corrcoef(rl[:, :-1].ravel(), rl[:, 1:].ravel())[0, 1]
            c2 = np.corrcoef(rl[:, :-2].ravel(), rl[:, 2:].ravel())[0, 1]
            corr.append((c1, c2))
        stds = np.median(np.array(stds), 0)
        res[name] = {"mean_code": float(best[:, 0].mean()),
                     "std_code_rgb": [float(s) for s in stds],
                     "std_10bit_cv_rgb": [float(s * 1023) for s in stds],
                     "corr_lag1": float(np.median([c[0] for c in corr])),
                     "corr_lag2": float(np.median([c[1] for c in corr])),
                     "patches_xy": [[int(b[2]), int(b[3])] for b in best], "patch": patch}
    return res


def temporal_noise(frames, Hs_list, t, masks, actor, levels=6):
    """Noise inside each window from stabilised neighbours: r = f_t - (w_{t-1} + w_{t+1})/2.

    Robust (MAD) per channel, binned by code level, in plate code values; also the
    lag-1/lag-2 spatial correlation of the residual (grain size).
    """
    h, w = frames[t].shape[:2]
    warp = []
    for n in (t - 1, t + 1):
        H = Hs_list[t] @ np.linalg.inv(Hs_list[n])
        warp.append(cv2.warpPerspective(frames[n], H, (w, h), flags=cv2.INTER_CUBIC))
    r = (frames[t] - 0.5 * (warp[0] + warp[1])) / np.sqrt(1.5)
    out = {}
    for k, m in masks.items():
        sel = (m > 0.99) & (actor < 0.5)
        sel[:4], sel[-4:], sel[:, :4], sel[:, -4:] = False, False, False, False
        if sel.sum() < 2000:
            continue
        lev = frames[t][sel].mean(1)
        rr = r[sel]
        edges = np.quantile(lev, np.linspace(0, 1, levels + 1))
        bins = []
        for a, b in zip(edges[:-1], edges[1:]):
            q = (lev >= a) & (lev <= b)
            mad = np.median(np.abs(rr[q] - np.median(rr[q], 0)), 0) * 1.4826
            bins.append({"code_level": float(lev[q].mean()), "std_code_rgb": [float(x) for x in mad],
                         "std_10bit_cv_rgb": [float(x * 1023) for x in mad]})
        rl = r.mean(2)
        s1 = sel[:, :-1] & sel[:, 1:]
        s2 = sel[:, :-2] & sel[:, 2:]
        c1 = np.corrcoef(rl[:, :-1][s1], rl[:, 1:][s1])[0, 1]
        c2 = np.corrcoef(rl[:, :-2][s2], rl[:, 2:][s2])[0, 1]
        out[k] = {"by_level": bins, "corr_lag1_h": float(c1), "corr_lag2_h": float(c2)}
    return out


# --------------------------------------------------------------------------- main
def run(shot: str):
    cfg = config.load(shot)
    pipe = colorpipe.ColorPipe(cfg)
    R = rg.load(cfg)
    ref = R["ref_frame"]
    out = config.work(cfg, "checkpoint1")
    frames = load_frames(cfg)
    N = len(frames)
    shape = frames[0].shape[:2]
    grays = [cv2.cvtColor(to8(f), cv2.COLOR_RGB2GRAY) for f in frames]
    summary = {"shot": shot, "frames": N, "start_tc": cfg["_start_tc"], "ref_frame": ref,
               "color": cfg["color"], "crop": cfg.get("crop")}

    # --- cuts inside the working range (must be none)
    cuts, resp = detect_cuts(grays)
    summary["cuts_in_range"] = cuts

    # --- motion
    mp = cfg["analysis"]["motion"]
    tr = motion.track(grays, R, ref, mp)
    mot = {}
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for plane, d in tr.items():
        polys = [r["poly"] for r in R["windows"].values() if r["plane"] == plane]
        disp = np.max([motion.displacement(d["H"], q) for q in polys], 0)
        step = np.max([[np.linalg.norm(cv2.perspectiveTransform(np.float64(q).reshape(-1, 1, 2), d["H"][i]) -
                                       cv2.perspectiveTransform(np.float64(q).reshape(-1, 1, 2), d["H"][i - 1]),
                                       axis=2).max() for i in range(1, N)] for q in polys], 0)
        mot[plane] = {"max_displacement_from_ref_px": float(disp.max()),
                      "max_frame_to_frame_px": float(step.max()),
                      "median_frame_to_frame_px": float(np.median(step)),
                      "locked_off": bool(disp.max() < mp["locked_off_px"]),
                      "ref_features": d["n_ref"],
                      "ecc_cc_min": float(d["ecc_cc"].min()), "ecc_cc_median": float(np.median(d["ecc_cc"])),
                      "frames_without_dense_confirmation": int((d["inliers"] < 0).sum()),
                      "spike_repaired_frames": d["repaired_frames"]}
        ax[0].plot(disp, label=f"{plane}: max vertex displacement vs ref")
        ax[1].plot(range(1, N), step, label=f"{plane}: frame-to-frame")
    ax[0].axvline(ref, color="k", ls=":", lw=1)
    ax[0].set_ylabel("px"); ax[1].set_ylabel("px"); ax[1].set_xlabel("frame (working range)")
    ax[0].legend(); ax[1].legend()
    ax[0].set_title(f"{shot} camera motion per window plane")
    fig.tight_layout(); fig.savefig(out / "motion.png", dpi=110); plt.close(fig)
    np.savez(config.work(cfg) / "motion.npz", **{p: d["H"] for p, d in tr.items()})
    summary["motion"] = mot
    Hs_at = lambda i: {p: d["H"][i] for p, d in tr.items()}

    # --- per-frame masks, stabilised median luminance in ref coords
    Ys, levels = [], {k: {"min_code": 1.0, "max_code": 0.0, "p001_code": [], "p9999_code": []} for k in R["windows"]}
    for i, f in enumerate(frames):
        lin = pipe.to_linear(f)
        Y = pipe.luminance(lin)
        Hs = Hs_at(i)
        H = next(iter(Hs.values()))
        Ys.append(cv2.warpPerspective(Y, np.linalg.inv(H), shape[::-1], flags=cv2.INTER_LINEAR) if i != ref else Y)
        masks = rg.frame_masks(R, shape, Hs)
        for k in R["windows"]:
            sel = masks[k] > 0.99
            v = f[sel]
            levels[k]["min_code"] = min(levels[k]["min_code"], float(v.min()))
            levels[k]["max_code"] = max(levels[k]["max_code"], float(v.max()))
            levels[k]["p001_code"].append(np.percentile(v, 0.1, axis=0))
            levels[k]["p9999_code"].append(np.percentile(v, 99.99, axis=0))
    for k, L in levels.items():
        p0 = np.median(np.array(L.pop("p001_code")), 0)
        p1 = np.max(np.array(L.pop("p9999_code")), 0)
        L["black_p0.1_code_rgb"] = [float(x) for x in p0]
        L["highlight_p99.99_code_rgb"] = [float(x) for x in p1]
        L["black_p0.1_lin_rgb"] = [float(x) for x in pipe.to_linear(p0)]
        L["highlight_p99.99_lin_rgb"] = [float(x) for x in pipe.to_linear(p1)]
        L["max_lin"] = float(pipe.to_linear(np.float32(L["max_code"])))
    summary["levels"] = levels
    Ymed = np.median(np.stack(Ys), 0).astype(np.float32)
    del Ys

    # --- blinds + transmission (ref coords)
    masks_ref = rg.frame_masks(R, shape)
    Yref_lin = pipe.luminance(pipe.to_linear(frames[ref]))
    actor = rg.hard_mask(R["actor_rough"]["poly"], shape)
    blinds = {}
    T = np.zeros(shape, np.float32)
    fg_union = np.zeros(shape, np.float32)
    for k in R["foreground"]:
        fg_union = np.maximum(fg_union, masks_ref[f"fg_{k}"])
    for k, reg in R["windows"].items():
        if not k.startswith("blinds"):
            continue
        b = blinds_analysis(Ymed, masks_ref[k], actor)
        blinds[k] = b
        if b:
            # until actor mattes exist the temporal median still contains the actors,
            # so the map is built from the reference frame itself
            T = np.maximum(T, transmission_map(Yref_lin, masks_ref[k], fg_union, b["slat_period_px"]))
    for k, reg in R["windows"].items():
        if k.startswith("door"):  # glass: uniform transmission, foreground objects removed
            T = np.maximum(T, masks_ref[k])
    summary["blinds"] = blinds
    sm = cfg["analysis"].get("transmission_smooth_px", 0)
    if sm > 0:  # proxy codecs: suppress macroblock structure in the map
        T = cv2.GaussianBlur(T, (0, 0), sm)
    tifffile.imwrite(config.work(cfg) / "transmission_ref.tif", T)

    # --- bokeh (ref frame, plus a few other frames for stability)
    bok = []
    excl_b = rg.hard_mask(R["actor_rough"]["poly"], shape) > 0
    for i in sorted({0, ref, N // 3, 2 * N // 3, N - 1}) if cfg["analysis"].get("bokeh", True) else []:
        Yi = pipe.luminance(pipe.to_linear(frames[i]))
        cands = find_bokeh(Yi, excl_b)[:8]
        for name, reg in R["foreground"].items():  # hand-marked interior bokeh discs
            if name.startswith("interior_bokeh"):
                c = np.mean(cv2.perspectiveTransform(np.float64(reg["poly"]).reshape(-1, 1, 2),
                                                     next(iter(tr.values()))["H"][i]).reshape(-1, 2), 0)
                cands.append((0.0, int(c[0]), int(c[1]), 60))
        for contrast, cx, cy, size in cands:
            b = measure_bokeh(Yi, cx, cy, half=int(size))
            if (b and not b["clipped_by_crop_edge"] and b["edge_10_90_px"] is not None
                    and 0.6 < b["aspect_v_over_h"] < 2.2 and b["minor_px"] > 12):
                b["frame"], b["contrast_vs_bg"] = i, contrast
                bok.append(b)
    keys = ["major_px", "minor_px", "aspect_v_over_h", "edge_10_90_px", "interior_cv", "rim_to_core_ratio"]
    summary["bokeh"] = {
        "n_measured": len(bok),
        "median": {k: float(np.median([b[k] for b in bok])) for k in keys} if bok else None,
        "samples": [{k: v for k, v in b.items() if not k.startswith("_")} for b in bok],
    }
    bok = sorted(bok, key=lambda b: -b["contrast_vs_bg"])[:6]

    # --- noise (ref frame, outside actors/regions edges, in plate code values)
    excl = (actor > 0) | (masks_ref["windows_all"] > 0.0)
    summary["noise"] = noise_analysis(frames[ref], excl, cfg["analysis"]["noise"]["patch"])
    Hlist = list(next(iter(tr.values()))["H"])
    win_masks = {k: masks_ref[k] for k in R["windows"]}
    summary["noise_temporal_in_windows"] = temporal_noise(frames, Hlist, ref, win_masks, actor)

    # --- quantisation / banding flag for the 8-bit proxies
    src_bits = cfg["_probe"]["bit_depth"]
    summary["source_bit_depth"] = src_bits
    for k in R["windows"]:
        sel = masks_ref[k] > 0.99
        g = frames[ref][..., 1][sel]
        uniq = np.unique(np.rint(g * (2 ** src_bits - 1)))
        summary["levels"][k]["distinct_green_codes_in_region"] = int(len(uniq))

    (config.work(cfg) / "analysis.json").write_text(json.dumps(summary, indent=2))
    render_checkpoint(cfg, R, frames, tr, T, bok, summary, out, pipe)
    return summary


def render_checkpoint(cfg, R, frames, tr, T, bok, summary, out, pipe):
    ref = R["ref_frame"]
    N = len(frames)
    prev = lambda i: to8(pipe.preview_709(frames[i]))
    Hs_at = lambda i: {p: d["H"][i] for p, d in tr.items()}
    # 1. overlays at ref, plus first/last frames (tracked)
    cv2.imwrite(str(out / "overlay_ref.png"), cv2.cvtColor(rg.draw_overlay(prev(ref), R), cv2.COLOR_RGB2BGR))
    strip = [cv2.resize(rg.draw_overlay(prev(i), R, Hs_at(i), labels=False), (640, 267)) for i in (0, N // 2, N - 1)]
    for s, i in zip(strip, (0, N // 2, N - 1)):
        cv2.putText(s, f"frame {i}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(out / "overlay_tracked_first_mid_last.png"), cv2.cvtColor(np.hstack(strip), cv2.COLOR_RGB2BGR))
    # 2. transmission map (+ zoom on a blinds patch)
    t8 = to8(T)
    cv2.imwrite(str(out / "transmission.png"), cv2.applyColorMap(t8, cv2.COLORMAP_INFERNO))
    for k, b in summary["blinds"].items():
        if not b:
            continue
        poly = np.array(R["windows"][k]["poly"])
        cx, cy = cfg["analysis"].get("zoom", {}).get(k, poly.mean(0).astype(int).tolist())
        zs = slice(max(cy - 60, 0), cy + 60), slice(max(cx - 80, 0), cx + 80)
        a = cv2.resize(prev(ref)[zs], None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        bimg = cv2.resize(cv2.applyColorMap(t8[zs], cv2.COLORMAP_INFERNO), None, fx=4, fy=4,
                          interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(str(out / f"transmission_zoom_{k}.png"), np.hstack([cv2.cvtColor(a, cv2.COLOR_RGB2BGR), bimg]))
    # 3. bokeh crops
    if bok:
        tiles = []
        for b in bok:
            x0, y0, crop, blob = b["_crop"]
            c8 = to8(np.clip(pipe.from_linear(crop), 0, 1))
            c8 = cv2.cvtColor(c8, cv2.COLOR_GRAY2BGR)
            cnt, _ = cv2.findContours(blob.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(c8, cnt, -1, (0, 255, 0), 1)
            cx, cy = b["center"][0] - x0, b["center"][1] - y0
            cv2.ellipse(c8, (int(cx), int(cy)), (int(b["minor_px"] / 2), int(b["major_px"] / 2)),
                        b["major_axis_angle_deg"] - 90, 0, 360, (0, 0, 255), 1)
            c8 = cv2.resize(c8, (280, 280), interpolation=cv2.INTER_NEAREST)
            cv2.putText(c8, f"f{b['frame']} {b['minor_px']:.0f}x{b['major_px']:.0f} edge {b['edge_10_90_px'] or 0:.0f}",
                        (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            tiles.append(c8)
        cv2.imwrite(str(out / "bokeh.png"), np.hstack(tiles))
    # 4. noise patches
    im = prev(ref).copy()
    for name, n in summary["noise"].items():
        for x, y in n["patches_xy"]:
            cv2.rectangle(im, (x, y), (x + n["patch"], y + n["patch"]),
                          (0, 255, 255) if name == "bright" else (255, 0, 255), 2)
    cv2.imwrite(str(out / "noise_patches.png"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    s = run(ap.parse_args().shot)
    print(json.dumps(s, indent=2))
