"""Step 4: composite the elements into the plate (scene-linear) + automated QC.

    python -m pipeline.comp shot01 --test        # 3 s test segment -> test/
    python -m pipeline.comp shot01 --full        # whole working range -> out/ (after approval)

Per frame: plate code -> linear; window masks / transmission tracked to the frame;
elements rendered in reference coordinates and warped; effects multiplied by
(1 - protection); inside the integrity matte the source pixels are copied
untouched; grain added only to the introduced difference; TPDF dither to the
10-bit grid only where the image changed; ProRes 4444 encode.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import tifffile

from . import colorpipe, config, media
from . import regions as rg
from .analyze import transmission_map
from .elements import Elements

ROOT = config.ROOT


# ------------------------------------------------------------------ helpers
def _read16(p):
    return cv2.imread(str(p), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0


def _smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def quiet_factor(cfg, n_frames):
    """Per-frame intensity multiplier from notes quiet_ranges (12-frame ease) x global_intensity."""
    notes = cfg["_notes"]
    fps = cfg["_fps"]
    q = np.ones(n_frames)
    base = config.tc_to_frames(cfg["_start_tc"], fps)
    lvl = float(notes.get("quiet_level", 0.25))
    ease = int(cfg["elements"].get("quiet_ease_frames", 12))
    for a, b in notes.get("quiet_ranges", []):
        fa, fb = config.tc_to_frames(a, fps) - base, config.tc_to_frames(b, fps) - base
        for i in range(n_frames):
            d = max(fa - i, i - fb, 0)  # frames outside the range
            w = 1.0 if d == 0 else max(0.0, 1 - d / ease)
            q[i] = min(q[i], 1 - (1 - lvl) * _smoothstep(w))
    return q * float(notes.get("global_intensity", 1.0)), [
        (config.tc_to_frames(a, fps) - base, config.tc_to_frames(b, fps) - base) for a, b in notes.get("quiet_ranges", [])]


def face_centres(cfg, i, objs):
    """Face centre per actor from the top band of its matte."""
    out = []
    md = config.work(cfg, "mattes")
    for o in objs.values():
        if not o.get("face"):
            continue
        a = _read16(md / f"alpha_{o['name']}" / f"{i:05d}.png")
        ys, xs = np.nonzero(a > 0.5)
        if len(ys) < 500:
            continue
        top = ys.min()
        band = (ys < top + 0.18 * a.shape[0])
        out.append((float(xs[band].mean()), float(ys[band].mean()) + 0.06 * a.shape[0]))
    return out


def face_attenuation(shape, centres, radius, level):
    if not centres:
        return np.ones(shape, np.float32)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    a = np.ones(shape, np.float32)
    for cx, cy in centres:
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        a = np.minimum(a, 1 - (1 - level) * _smoothstep(1 - d / radius))
    return a


def noise_sigma_fn(analysis, region):
    nt = analysis.get("noise_temporal_in_windows", {}).get(region)
    if not nt:
        return lambda lev: np.full(lev.shape + (3,), 0.0015, np.float32)
    lv = np.array([b["code_level"] for b in nt["by_level"]])
    sd = np.array([b["std_code_rgb"] for b in nt["by_level"]])
    return lambda lev: np.stack([np.interp(lev, lv, sd[:, c]) for c in range(3)], -1).astype(np.float32)


def soft_knee(x, cap, knee=0.85):
    k = knee * cap
    over = np.maximum(x - k, 0)
    return np.where(x > k, k + (cap - k) * (1 - np.exp(-over / np.maximum(cap - k, 1e-6))), x)


def limit_brightening(lin, new, cap):
    """Brightening rolls off smoothly so the result never exceeds `cap` (the plate's own
    max in the region); darkening is untouched. Zero change stays zero change."""
    up = new > lin
    gain = (soft_knee(new, cap) - soft_knee(lin, cap)) * np.clip(
        (cap - lin) / np.maximum(cap - soft_knee(lin, cap), 1e-6), 0, 1)
    return np.where(up, lin + np.maximum(gain, 0), new)


def pick_test_window(cfg, R, Hs_all, length):
    """Start frame of the `length`-frame window with the most unprotected window area."""
    N = cfg["_count"]
    shape = (cfg["crop"]["h"], cfg["crop"]["w"]) if cfg.get("crop") else (cfg["_probe"]["height"], cfg["_probe"]["width"])
    vis = []
    for i in range(N):
        m = rg.frame_masks(R, shape, {p: H[i] for p, H in Hs_all.items()})["windows_all"]
        prot = _read16(config.work(cfg, "mattes", "protection") / f"{i:05d}.png")
        vis.append(float((m * (1 - prot)).mean()))
    vis = np.array(vis)
    if N <= length:
        return 0, vis
    s = np.convolve(vis, np.ones(length), "valid")
    return int(np.argmax(s)), vis


# ------------------------------------------------------------------ main render
def render(shot: str, mode: str, limit: int | None = None):
    cfg = config.load(shot)
    pipe = colorpipe.ColorPipe(cfg)
    R = rg.load(cfg)
    analysis = json.loads((config.work(cfg) / "analysis.json").read_text())
    P = json.loads((ROOT / "config" / "prompts" / f"{shot}.json").read_text())
    objs = {int(k): v for k, v in P["objects"].items()}
    mot = np.load(config.work(cfg) / "motion.npz")
    Hs_all = {k: mot[k] for k in mot.files}
    fps = cfg["_fps"]
    N = cfg["_count"]
    frames = sorted(config.work(cfg, "frames").glob("*.tif"))
    shape = tifffile.imread(frames[0]).shape[:2]
    e = cfg["elements"]

    if mode == "test":
        tcfg = cfg["test"]
        length = int(tcfg["length_frames"])
        start = tcfg.get("start_frame")
        vis = None
        if start is None:
            start, vis = pick_test_window(cfg, R, Hs_all, length)
        idx = list(range(start, min(start + (limit or length), N)))
        out_dir = ROOT / "test"
        tag = f"{shot}"
    else:
        idx = list(range(N))
        out_dir = ROOT / "out" / shot
        tag = f"{shot}"
    out_dir.mkdir(parents=True, exist_ok=True)
    qdir = ROOT / "qc"
    qdir.mkdir(exist_ok=True)
    stills = config.work(cfg, "checkpoint3")

    el = Elements(cfg, pipe, shape, fps, N / fps)
    q, quiet = quiet_factor(cfg, N)
    rng = np.random.default_rng(cfg["seed"] + 1234)
    fw_quiet = np.array([any(a - 12 <= i <= b + 12 for a, b in quiet) for i in range(N)])

    # caps against clipping: never above the plate's own max in each region
    white = float(pipe.to_linear(np.float32(e.get("max_code", 0.985))))  # never push a pixel to full white
    caps = {k: np.minimum(np.array(analysis["levels"][k]["highlight_p99.99_lin_rgb"], np.float32), white)
            for k in R["windows"]}
    sig = {k: noise_sigma_fn(analysis, k) for k in R["windows"]}
    period = {k: (analysis["blinds"].get(k) or {}).get("slat_period_px", 12.0) for k in R["windows"]}
    tsm = cfg["analysis"].get("transmission_smooth_px", 0)
    tc0 = config.plate_tc(cfg, cfg["_first"] + idx[0])
    transfer = cfg["color"]["input_transfer"]
    comp_path = out_dir / (f"{tag}_comp_{transfer}.mov" if mode == "test" else f"{tag}_comp_{transfer}_ProRes4444XQ.mov")
    h, w = shape
    writer = media.ProResWriter(comp_path, cfg, w, h, profile="4444" if mode == "test" else "4444xq",
                                timecode=tc0, reel=cfg["_probe"].get("reel_name"))
    # previews restore the letterbox
    cr = cfg.get("crop") or {"x": 0, "y": 0, "w": w, "h": h}
    full_h, full_w = cfg["_probe"]["height"], cfg["_probe"]["width"]
    fps_s = f"{cfg['_probe']['fps_num']}/{cfg['_probe']['fps_den']}"
    prev = media.H264Writer(out_dir / f"{tag}_preview_709.mp4", fps_s, full_w * 2, full_h)
    elv = media.H264Writer(out_dir / f"{tag}_elements_only.mp4", fps_s, full_w, full_h)

    def bars(img):
        canvas = np.zeros((full_h, full_w, 3), np.float32)
        canvas[cr["y"]:cr["y"] + cr["h"], cr["x"]:cr["x"] + cr["w"]] = img
        return canvas

    S = el.ls
    Sm = np.diag([1 / S, 1 / S, 1]).astype(np.float64)
    stats = []
    t_start = time.time()
    for n, i in enumerate(idx):
        t = i / fps
        src = tifffile.imread(frames[i]).astype(np.float32) / 65535.0
        lin = pipe.to_linear(src)
        Hs = {p: H[i] for p, H in Hs_all.items()}
        H = next(iter(Hs.values()))
        masks = rg.frame_masks(R, shape, Hs)
        prot = _read16(config.work(cfg, "mattes", "protection") / f"{i:05d}.png")
        integ = cv2.imread(str(config.work(cfg, "mattes", "integrity") / f"{i:05d}.png"), cv2.IMREAD_GRAYSCALE) > 0
        keep = 1.0 - prot
        Y = pipe.luminance(lin)
        fg_union = np.zeros(shape, np.float32)
        for k in R["foreground"]:
            fg_union = np.maximum(fg_union, masks[f"fg_{k}"])

        # intensity modifiers
        qi = float(q[i])
        faces = face_centres(cfg, i, objs)
        fa = face_attenuation(shape, faces, e["faces"]["radius_px"], e["faces"]["intensity_level"])
        near_face_door = any(abs(cx - (e["door_bokeh"]["bbox_px"][0] + e["door_bokeh"]["bbox_px"][2]) / 2) <
                             e["faces"]["radius_px"] for cx, _ in faces)

        # elements (reference coords) -> this frame
        L, O = el.light_field(t, qi)
        Hl = Sm @ H @ np.linalg.inv(Sm)
        lw, lh = el.lw, el.lh
        Lw = cv2.warpPerspective(L, Hl, (lw, lh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        Ow = cv2.warpPerspective(O, Hl, (lw, lh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        Lf = cv2.resize(Lw, (w, h), interpolation=cv2.INTER_CUBIC)
        Of = cv2.resize(Ow, (w, h), interpolation=cv2.INTER_CUBIC)
        fw_gain = el.fireworks(t, 0.0 if fw_quiet[i] else qi)

        out = lin.copy()
        nofw = lin.copy()  # everything except the fireworks (for the >3 Hz oscillation test)
        layers = {"blinds": np.zeros_like(lin), "door": np.zeros_like(lin), "fireworks": np.zeros_like(lin)}
        for k, reg in R["windows"].items():
            m = np.where(masks[k] < 1e-3, 0.0, masks[k]) * keep  # hard zero beyond the feather tail
            if m.max() <= 0:
                continue
            kind = reg.get("kind", "blinds")
            if kind == "blinds":
                T = transmission_map(Y, masks[k], fg_union, period[k])
                if tsm > 0:
                    T = cv2.GaussianBlur(T, (0, 0), tsm)
            elif kind == "diffuse_glass":
                Ys = cv2.GaussianBlur(Y, (0, 0), 6)
                ref_level = np.percentile(Ys[masks[k] > 0.98], 95) if (masks[k] > 0.98).any() else Ys.max()
                T = np.clip(Ys / max(ref_level, 1e-6), 0, 1) * masks[k] * (1 - fg_union)
            else:
                T = masks[k] * (1 - fg_union)
            T = T * fa  # quieter right next to faces
            T3 = T[..., None]
            if kind in ("blinds", "diffuse_glass"):
                kk = e["light_field"]["k_" + kind]
                Lk = Lf if kind == "blinds" else cv2.GaussianBlur(Lf, (0, 0), e["light_field"]["diffuse_extra_blur_px"])
                Ok = Of if kind == "blinds" else cv2.GaussianBlur(Of, (0, 0), e["light_field"]["diffuse_extra_blur_px"])
                if e["light_field"].get("mode", "multiplicative") == "additive_relative":
                    # new light sources (props, floats, foam) ADD light through the gaps, scaled to the
                    # local backlight level (achromatic) so their colour really reads; bodies and flags
                    # still block the existing street light multiplicatively
                    Yb = cv2.GaussianBlur(Y, (0, 0), e["light_field"].get("base_blur_px", 40))[..., None]
                    new_b = lin * (1 - T3 * Ok[..., None]) + kk * T3 * Lk * Yb
                else:
                    new_b = lin * (1 + kk * T3 * Lk) * (1 - T3 * Ok[..., None])
                new = new_b * (1 + T3 * fw_gain)
                layers["blinds"] += (new_b - lin) * m[..., None]
                layers["fireworks"] += (new - new_b) * m[..., None]
            else:  # clear glass: bokeh added under the reflections, soft passer shadows, flash
                bok = el.door_bokeh(t, scale=qi, blink_scale=e["faces"]["blink_depth"] if near_face_door else 1.0)
                bok = cv2.warpPerspective(bok, H, (w, h), flags=cv2.INTER_LINEAR)
                Od = cv2.resize(cv2.warpPerspective(el.door_occlusion(t), Hl, (lw, lh), flags=cv2.INTER_LINEAR,
                                                    borderMode=cv2.BORDER_REPLICATE), (w, h),
                                interpolation=cv2.INTER_CUBIC) * qi
                # the lit parade street behind the glass, with the crowd as very soft dark shapes
                da = e.get("door_ambient", {})
                amb = np.zeros_like(lin)
                if da.get("level_lin", 0) > 0:
                    # structured, not flat: mostly the light field (wash, beams, crowd lights), a little base
                    amb = da["level_lin"] * (da.get("base", 0.3) * el.lin_color(da["color"], da.get("desaturate", 0.3))
                                             + da.get("light_field_gain", 1.0) * Lf)
                sil = np.clip(Od * da.get("silhouette_gain", 1.0), 0, 0.95)[..., None]
                new_b = lin * (1 - T3 * Od[..., None] * da.get("plate_occlusion", 1.0)) + T3 * (bok + amb * (1 - sil))
                new = new_b + lin * T3 * fw_gain * e["fireworks"]["door_scale"]
                layers["door"] += (new_b - lin) * m[..., None]
                layers["fireworks"] += (new - new_b) * m[..., None]
            new = limit_brightening(lin, new, caps[k])  # never above the plate's max
            out = out + (new - lin) * m[..., None]
            nofw = nofw + (limit_brightening(lin, new_b, caps[k]) - lin) * m[..., None]

        # back to code values; grain on the introduced difference only
        code = pipe.from_linear(np.maximum(out, 0))
        diff = code - src
        changed = np.abs(diff).max(-1) > 1e-6
        if e["grain"]["enabled"] and changed.any():
            g = rng.standard_normal(src.shape).astype(np.float32)
            g = cv2.GaussianBlur(g, (0, 0), e["grain"]["blur_px"])
            g /= max(float(g.std()), 1e-6)
            sg = np.zeros_like(src)
            for k in R["windows"]:
                mk = masks[k] > 0
                if mk.any():
                    so, ss = sig[k](code[mk].mean(-1)), sig[k](src[mk].mean(-1))
                    ratio = np.clip(code[mk] / np.maximum(src[mk], 1e-4), 0, 4)
                    sg[mk] = np.maximum(sg[mk], np.sqrt(np.maximum(so ** 2 - (ss * ratio) ** 2, 0)))
            # only as much grain as the change itself warrants, faded with the effect
            sg *= np.clip(np.abs(diff) / np.maximum(sg, 1e-6), 0, 1)
            code = code + g * sg * e["grain"]["amount"] * (keep[..., None] > 0)
        code = np.where(changed[..., None], media.dither_to_10bit(code, rng), src)
        hot = src >= e.get("max_code", 0.985)
        code = np.where(hot, src, code)  # a channel already at the plate's white is never pushed further
        code[integ] = src[integ]  # hard guarantee: actor core untouched
        writer.write(np.clip(code, 0, 1))

        # QC numbers (pre-encode)
        d = np.abs(code - src).max(-1)
        outside = masks["windows_all"] < 1e-3
        spill_zone = np.zeros(shape, bool)
        Yo = pipe.luminance(pipe.to_linear(code))
        wm = masks["windows_all"] * keep
        stats.append({
            "frame": i, "tc": config.plate_tc(cfg, cfg["_first"] + i),
            "integrity_max_pre_encode": float(d[integ].max()) if integ.any() else 0.0,
            "outside_regions_max": float(d[outside & ~spill_zone].max()) if outside.any() else 0.0,
            "actor_protection_max": float(d[prot >= 0.999].max()) if (prot >= 0.999).any() else 0.0,
            "win_lum_src": float((Y * wm).sum() / max(wm.sum(), 1)),
            "win_lum_out": float((Yo * wm).sum() / max(wm.sum(), 1)),
            "win_lum_nofw": float((pipe.luminance(np.maximum(nofw, 0)) * wm).sum() / max(wm.sum(), 1)),
            "new_clipped_px": int(((src < 0.995) & (code >= 0.999)).any(-1)[masks["windows_all"] > 0].sum()),
            "changed_px": int(changed.sum()),
            "local_change_p95": float(np.percentile(np.abs(pipe.luminance(pipe.to_linear(code)) / np.maximum(Y, 1e-5) - 1)[
                (masks["windows_all"] > 0.9) & (keep > 0.99) & (Y > 1e-3)], 95))
            if ((masks["windows_all"] > 0.9) & (keep > 0.99)).any() else 0.0,
            "faces": faces,
        })

        # previews
        before, after = pipe.preview_709(src), pipe.preview_709(code)
        prev.write(np.hstack([bars(before), bars(after)]))
        dd = code - src
        pos = np.clip(dd * 4, 0, 1)
        neg = np.clip(-dd.mean(-1) * 4, 0, 1)[..., None] * np.array([0.6, 0.2, 1.0], np.float32)
        elv.write(bars(np.clip(pos + neg, 0, 1)))
        if n in (0, len(idx) // 3, 2 * len(idx) // 3, len(idx) - 1) or n % 15 == 0:
            cv2.imwrite(str(stills / f"f{i:03d}_before_after.jpg"),
                        cv2.cvtColor((np.hstack([before, after]) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            cv2.imwrite(str(stills / f"f{i:03d}_elements_x4.jpg"),
                        cv2.cvtColor((np.clip(pos + neg, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
        if n % 10 == 0:
            print(f"  frame {i} ({n + 1}/{len(idx)})  {time.time() - t_start:.0f}s", flush=True)
    writer.close()
    prev.close()
    elv.close()
    (config.work(cfg) / f"render_stats_{mode}.json").write_text(json.dumps(stats, indent=1))
    used = {k: v for k, v in cfg.items() if not k.startswith("_")}
    (out_dir / f"{tag}_config_used.json").write_text(json.dumps(used, indent=2))
    report = run_qc(cfg, pipe, comp_path, idx, stats, el, mode)
    print(report)


# ------------------------------------------------------------------ QC
def run_qc(cfg, pipe, comp_path, idx, stats, el, mode):
    fps = cfg["_fps"]
    frames = sorted(config.work(cfg, "frames").glob("*.tif"))
    # post-encode: decode the written ProRes through the same path as the plate
    qcfg = dict(cfg, plate=str(comp_path), crop=None, _probe=media.probe(comp_path)["summary"])
    post = []
    for n, (_, img) in enumerate(media.read_frames(qcfg, 0, len(idx), crop=False)):
        i = idx[n]
        src = tifffile.imread(frames[i]).astype(np.float32) / 65535.0
        integ = cv2.imread(str(config.work(cfg, "mattes", "integrity") / f"{i:05d}.png"), cv2.IMREAD_GRAYSCALE) > 0
        d = np.abs(img - src)[integ] * 1023
        post.append((float(d.max()), float(np.percentile(d, 99.9))))
    post = np.array(post)
    base_path = config.work(cfg) / f"codec_baseline_{mode}.mov"
    bw = media.ProResWriter(base_path, cfg, qcfg["_probe"]["width"], qcfg["_probe"]["height"],
                            profile="4444" if mode == "test" else "4444xq")
    for i in idx:
        bw.write(tifffile.imread(frames[i]).astype(np.float32) / 65535.0)
    bw.close()
    bcfg = dict(cfg, plate=str(base_path), crop=None, _probe=media.probe(base_path)["summary"])
    base = []
    for n, (_, img) in enumerate(media.read_frames(bcfg, 0, len(idx), crop=False)):
        src = tifffile.imread(frames[idx[n]]).astype(np.float32) / 65535.0
        integ = cv2.imread(str(config.work(cfg, "mattes", "integrity") / f"{idx[n]:05d}.png"), cv2.IMREAD_GRAYSCALE) > 0
        d = np.abs(img - src)[integ] * 1023
        base.append((float(d.max()), float(np.percentile(d, 99.9))))
    base = np.array(base)
    pre_int = max(s["integrity_max_pre_encode"] for s in stats)
    outside = max(s["outside_regions_max"] for s in stats)
    prot_max = max(s["actor_protection_max"] for s in stats)
    clipped = sum(s["new_clipped_px"] for s in stats)
    # flash rule on the window area: introduced luminance modulation above 3 Hz
    lo = np.array([s["win_lum_out"] for s in stats])
    ls = np.array([s["win_lum_src"] for s in stats])
    rel = (lo - ls) / np.maximum(ls, 1e-6)
    # (a) sustained oscillation: >3 Hz content of everything except the (single-event) fireworks
    rel_nf = (np.array([s["win_lum_nofw"] for s in stats]) - ls) / np.maximum(ls, 1e-6)
    spec = np.abs(np.fft.rfft(rel_nf - rel_nf.mean()))
    fr = np.fft.rfftfreq(len(rel_nf), 1 / fps)
    hf_amp = float(np.sqrt(2 * (spec[fr > 3] ** 2).sum()) / len(rel_nf))  # rms of >3 Hz part, relative lum
    # flashes: rises of >8% relative window luminance within 2 frames
    rises = np.where(np.diff(rel, prepend=rel[0]) > 0.08)[0]
    onsets = [r for k, r in enumerate(rises) if k == 0 or r - rises[k - 1] > 2]
    max_per_s = max([sum(1 for o in onsets if a <= o < a + fps) for a in range(len(rel))] or [0])
    passed = {
        "actor_integrity_pre_encode": pre_int == 0.0,
        "actor_fully_protected_zone": prot_max == 0.0,
        "region_containment": outside == 0.0,
        "flash_rule_<=3/s": max_per_s <= 3 and hf_amp < 0.005,
        "no_new_clipping": clipped == 0,
    }
    lines = [f"# QC — {cfg['shot']} ({mode})", "",
             f"Comp: `{Path(comp_path).relative_to(ROOT)}` · frames {idx[0]}–{idx[-1]} "
             f"(TC {stats[0]['tc']} – {stats[-1]['tc']}) · {len(idx)} frames", "",
             "| check | result | value |", "|---|---|---|",
             f"| actor integrity, pre-encode (eroded matte, output == decoded source) | {'PASS' if passed['actor_integrity_pre_encode'] else 'FAIL'} | max diff {pre_int:.2e} |",
             f"| actor fully-protected zone untouched (protection = 1) | {'PASS' if passed['actor_fully_protected_zone'] else 'FAIL'} | max diff {prot_max:.2e} |",
             f"| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max {post[:, 0].max():.2f} · p99.9 {post[:, 1].max():.2f} (worst frame) |",
             f"| codec baseline: untouched source through the same encode (10-bit CV) | info | max {base[:, 0].max():.2f} · p99.9 {base[:, 1].max():.2f} |",
             f"| region containment (diff outside windows) | {'PASS' if passed['region_containment'] else 'FAIL'} | max {outside:.2e} |",
             f"| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | {'PASS' if passed['flash_rule_<=3/s'] else 'FAIL'} | >3 Hz rms {hf_amp * 100:.3f} % of window lum · max onsets/s {max_per_s} |",
             f"| new clipping in windows | {'PASS' if passed['no_new_clipping'] else 'FAIL'} | {clipped} px total |",
             f"| banding | flag | source is {cfg['_probe']['bit_depth']}-bit {cfg['_probe']['codec']}: banding/blocking in the plate itself is not fought (proxy) |",
             "", "Window luminance change introduced (relative): "
             f"mean {rel.mean() * 100:+.2f} %, min {rel.min() * 100:+.2f} %, max {rel.max() * 100:+.2f} %  ·  "
             f"local change in visible window area (p95 per frame): median "
             f"{np.median([s['local_change_p95'] for s in stats]) * 100:.1f} %, max "
             f"{max(s['local_change_p95'] for s in stats) * 100:.1f} %", "",
             "Per-frame post-encode integrity (10-bit CV, max / p99.9):", "",
             "| frame | TC | max | p99.9 |", "|---|---|---|---|"]
    for n, s in enumerate(stats):
        if n % 5 == 0 or n == len(stats) - 1:
            lines.append(f"| {s['frame']} | {s['tc']} | {post[n, 0]:.2f} | {post[n, 1]:.2f} |")
    lines += ["", "Fireworks scheduled (s from start of working range): " +
              ", ".join(f"{b['t']:.2f}" for b in el.fw), ""]
    rep = "\n".join(lines)
    (ROOT / "qc" / f"{cfg['shot']}_report{'_test' if mode == 'test' else ''}.md").write_text(rep)
    (config.work(cfg) / f"qc_{mode}.json").write_text(json.dumps({"passed": passed, "post_encode": post.tolist(),
                                                                  "rel_lum": rel.tolist()}, indent=1))
    if not all(passed.values()):
        print("QC FAILED:", {k: v for k, v in passed.items() if not v})
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    ap.add_argument("--frames", type=int, default=None, help="test only: render just the first N frames")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--test", action="store_true")
    g.add_argument("--full", action="store_true")
    a = ap.parse_args()
    render(a.shot, "test" if a.test else "full", a.frames)
