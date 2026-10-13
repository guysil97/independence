"""Step 2: actor mattes -> CHECKPOINT 2.

    python -m pipeline.mattes shot02 sam      # SAM 2.1 video propagation (slow on CPU)
    python -m pipeline.mattes shot02 refine   # guided-filter alpha, temporal smoothing, protection
    python -m pipeline.mattes shot02 qc       # QC frames + videos
    python -m pipeline.mattes shot02 all

Outputs in work/<shot>/mattes/:
  raw/obj<id>/#####.png        SAM probability (8-bit)
  alpha_<name>/#####.png       refined soft alpha per object (16-bit)
  actors_alpha/#####.png       union alpha (16-bit)
  protection/#####.png         union alpha + ~12 px soft falloff, temporally stabilised (16-bit)
  integrity/#####.png          union alpha > 0.5 eroded 3 px (8-bit, 255 = must be untouched)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
import tifffile

from . import config

ROOT = config.ROOT
SAM_MODELS = {
    "small": ("configs/sam2.1/sam2.1_hiera_s.yaml", "sam2.1_hiera_small.pt"),
    "base_plus": ("configs/sam2.1/sam2.1_hiera_b+.yaml", "sam2.1_hiera_base_plus.pt"),
    "large": ("configs/sam2.1/sam2.1_hiera_l.yaml", "sam2.1_hiera_large.pt"),
}


def _prompts(cfg):
    return json.loads((ROOT / "config" / "prompts" / f"{cfg['shot']}.json").read_text())


def _device():
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


# --------------------------------------------------------------------------- SAM 2
def run_sam(cfg):
    import torch
    from sam2.build_sam import build_sam2_video_predictor

    mc = cfg.get("mattes", {})
    yaml, ckpt = SAM_MODELS[mc.get("sam_model", "base_plus")]
    ckpt = ROOT / "third_party" / "sam2" / "checkpoints" / ckpt
    dev = _device()
    torch.set_num_threads(os.cpu_count() or 4)
    pred = build_sam2_video_predictor(yaml, str(ckpt), device=dev)
    P = _prompts(cfg)
    jpg = config.work(cfg, "jpg")
    t0 = time.time()
    with torch.inference_mode():
        state = pred.init_state(video_path=str(jpg), offload_video_to_cpu=True, offload_state_to_cpu=True)
        first = {}
        for p in P["prompts"]:
            oid = int(p["obj_id"])
            first[oid] = min(first.get(oid, 1 << 30), p["frame"])
            pts = np.array([q[:2] for q in p.get("points", [])], np.float32) if p.get("points") else None
            lab = np.array([q[2] for q in p.get("points", [])], np.int32) if p.get("points") else None
            box = np.array(p["box"], np.float32) if p.get("box") else None
            pred.add_new_points_or_box(state, frame_idx=p["frame"], obj_id=oid, points=pts, labels=lab, box=box)
        out_dir = config.work(cfg, "mattes", "raw")
        N = state["num_frames"]
        results = {}
        start_rev = max(first.values())  # backward pass only needs frames before the latest first prompt
        passes = [(False, {})] + ([(True, {"start_frame_idx": start_rev, "max_frame_num_to_track": start_rev})]
                                  if start_rev > 0 else [])
        for reverse, kw in passes:
            for f, ids, logits in pred.propagate_in_video(state, reverse=reverse, **kw):
                for oid, lg in zip(ids, logits):
                    # forward pass owns frames from the object's first prompt on; reverse the rest
                    if reverse == (f < first[int(oid)]):
                        results[(int(oid), f)] = torch.sigmoid(lg[0]).float().cpu().numpy()
                if f % 20 == 0:
                    print(f"  {'rev' if reverse else 'fwd'} frame {f}/{N}  {time.time() - t0:.0f}s", flush=True)
    for (oid, f), prob in results.items():
        d = config.work(cfg, "mattes", "raw", f"obj{oid}")
        cv2.imwrite(str(d / f"{f:05d}.png"), np.clip(np.rint(prob * 255), 0, 255).astype(np.uint8))
    print(f"SAM 2 ({mc.get('sam_model', 'base_plus')}, {dev}) done in {time.time() - t0:.0f}s")


# --------------------------------------------------------------------------- refine
def _guided_alpha(rgb, prob, mc):
    """SAM binary -> dilate -> guided filter with the plate as guide -> soft alpha."""
    hard = (prob > 0.5).astype(np.uint8)
    d = int(mc.get("dilate_px", 8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * d + 1, 2 * d + 1))
    dil = cv2.dilate(hard, k).astype(np.float32)
    ero = cv2.erode(hard, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * d + 1, 2 * d + 1))).astype(np.float32)
    guide = np.clip(rgb ** (1 / 2.2), 0, 1).astype(np.float32)  # perceptual guide works better on dark plates
    a = cv2.ximgproc.guidedFilter(guide, hard.astype(np.float32), int(mc.get("gf_radius", 8)),
                                  float(mc.get("gf_eps", 1e-3)))
    # the soft edge lives only in the dilated band; the eroded core is solid
    a = np.clip(a, 0, 1) * dil
    return np.maximum(a, ero)


def _flow(a, b):
    """Dense flow a->b at half res (grayscale uint8), returned at full res in px."""
    s = 0.5
    a2 = cv2.resize(a, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    b2 = cv2.resize(b, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    f = cv2.calcOpticalFlowFarneback(a2, b2, None, 0.5, 4, 21, 3, 7, 1.5, 0)
    return cv2.resize(f, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_LINEAR) / s


def _warp(img, flow):
    """Sample img at x + flow(x) (flow from the target frame to img's frame)."""
    h, w = flow.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(img, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _protection(alpha, mc):
    """alpha + soft falloff of `protect_px`: 1 inside the actor, smoothstep to 0 at protect_px."""
    px = float(mc.get("protect_px", 12))
    hard = (alpha > 0.02).astype(np.uint8)
    dist = cv2.distanceTransform(1 - hard, cv2.DIST_L2, 5)
    t = np.clip(1 - dist / px, 0, 1)
    fall = t * t * (3 - 2 * t)
    return np.maximum(alpha, fall).astype(np.float32)


def run_refine(cfg):
    mc = cfg.get("mattes", {})
    P = _prompts(cfg)
    frames = sorted(config.work(cfg, "frames").glob("*.tif"))
    N = len(frames)
    objs = {int(k): v for k, v in P["objects"].items()}
    t0 = time.time()
    rgbs, grays, alphas = [], [], {o: [] for o in objs}
    for i, f in enumerate(frames):
        rgb = tifffile.imread(f).astype(np.float32) / 65535.0
        rgbs.append(rgb)
        grays.append(cv2.cvtColor(np.rint(rgb * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY))
        for o in objs:
            pth = config.work(cfg, "mattes", "raw", f"obj{o}") / f"{i:05d}.png"
            prob = cv2.imread(str(pth), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255 if pth.exists() \
                else np.zeros(rgb.shape[:2], np.float32)
            alphas[o].append(_guided_alpha(rgb, prob, mc))
    print(f"  guided filter {time.time() - t0:.0f}s")
    union = [np.max([alphas[o][i] for o in objs if objs[o].get("protect", True)], 0) for i in range(N)]
    # temporal stabilisation of the protection matte: flow-compensated [1/4, 1/2, 1/4] over +-1 frame,
    # accepted only where the warp is photometrically consistent (no lag on fast motion);
    # the current frame's own alpha is always fully inside the result.
    prot_raw = [_protection(a, mc) for a in union]
    w_side = float(mc.get("temporal_side_weight", 0.25))
    tol = float(mc.get("temporal_consistency", 12.0))  # 8-bit grey levels
    prot = []
    for i in range(N):
        acc = prot_raw[i] * (1 - 2 * w_side)
        wsum = np.full(union[i].shape, 1 - 2 * w_side, np.float32)
        for j in (i - 1, i + 1):
            if not 0 <= j < N:
                continue
            fl = _flow(grays[i], grays[j])
            wg = _warp(grays[j].astype(np.float32), fl)
            ok = (np.abs(wg - grays[i]) < tol).astype(np.float32) * w_side
            acc += _warp(prot_raw[j], fl) * ok
            wsum += ok
        prot.append(np.maximum(acc / wsum, union[i]))
    print(f"  temporal {time.time() - t0:.0f}s")
    er = int(mc.get("integrity_erode_px", 3))
    ke = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * er + 1, 2 * er + 1))
    for name in ["actors_alpha", "protection", "integrity"] + [f"alpha_{objs[o]['name']}" for o in objs]:
        config.work(cfg, "mattes", name)
    md = config.work(cfg, "mattes")
    stats = []
    for i in range(N):
        to16 = lambda a: np.clip(np.rint(a * 65535), 0, 65535).astype(np.uint16)
        cv2.imwrite(str(md / "actors_alpha" / f"{i:05d}.png"), to16(union[i]))
        cv2.imwrite(str(md / "protection" / f"{i:05d}.png"), to16(prot[i]))
        integ = cv2.erode((union[i] > 0.5).astype(np.uint8), ke) * 255
        cv2.imwrite(str(md / "integrity" / f"{i:05d}.png"), integ)
        for o in objs:
            cv2.imwrite(str(md / f"alpha_{objs[o]['name']}" / f"{i:05d}.png"), to16(alphas[o][i]))
        stats.append({o: float((alphas[o][i] > 0.5).mean()) for o in objs})
    # temporal chatter metric on the protection edge band: mean |dP| per frame (after camera-flow compensation)
    chatter = []
    for i in range(1, N):
        fl = _flow(grays[i], grays[i - 1])
        band = (prot[i] > 0.02) & (prot[i] < 0.98)
        d = np.abs(_warp(prot[i - 1], fl) - prot[i])[band]
        chatter.append(float(d.mean()) if d.size else 0.0)
    (md / "refine_stats.json").write_text(json.dumps({"coverage": stats, "edge_chatter": chatter}, indent=1))
    print(f"refine done {time.time() - t0:.0f}s; median edge chatter {np.median(chatter):.4f}")


# --------------------------------------------------------------------------- QC
def run_qc(cfg, frames_of_interest=None):
    from .colorpipe import ColorPipe
    from .media import H264Writer

    pipe = ColorPipe(cfg)
    P = _prompts(cfg)
    objs = {int(k): v for k, v in P["objects"].items()}
    md = config.work(cfg, "mattes")
    qd = config.work(cfg, "checkpoint2")
    frames = sorted(config.work(cfg, "frames").glob("*.tif"))
    N = len(frames)
    cols = [(255, 60, 60), (60, 200, 255), (255, 220, 0), (120, 255, 120)]
    fps = f"{cfg['_probe']['fps_num']}/{cfg['_probe']['fps_den']}"
    h, w = 800, 1920
    vid_line = H264Writer(qd / f"{cfg['shot']}_matte_edges.mp4", fps, w, h)
    vid_red = H264Writer(qd / f"{cfg['shot']}_matte_red.mp4", fps, w, h)

    def render(i):
        rgb = pipe.preview_709(tifffile.imread(frames[i]).astype(np.float32) / 65535.0)
        line = (rgb * 255).astype(np.uint8).copy()
        for k, o in enumerate(objs):
            a = cv2.imread(str(md / f"alpha_{objs[o]['name']}" / f"{i:05d}.png"), cv2.IMREAD_UNCHANGED) / 65535.0
            cnt, _ = cv2.findContours((a > 0.5).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(line, cnt, -1, cols[k % 4], 1, cv2.LINE_AA)
        prot = cv2.imread(str(md / "protection" / f"{i:05d}.png"), cv2.IMREAD_UNCHANGED) / 65535.0
        cnt, _ = cv2.findContours((prot > 0.02).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(line, cnt, -1, (255, 255, 255), 1, cv2.LINE_AA)
        al = cv2.imread(str(md / "actors_alpha" / f"{i:05d}.png"), cv2.IMREAD_UNCHANGED)[..., None] / 65535.0
        red = rgb * (1 - 0.55 * al) + np.array([1.0, 0.0, 0.0]) * 0.55 * al
        red = (np.clip(red, 0, 1) * 255).astype(np.uint8)
        for im in (line, red):
            cv2.putText(im, f"{cfg['shot']} f{i}  {config.plate_tc(cfg, cfg['_first'] + i)}", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        return line, red, al[..., 0], rgb

    for i in range(N):
        line, red, _, _ = render(i)
        vid_line.write(line / 255.0)
        vid_red.write(red / 255.0)
    vid_line.close()
    vid_red.close()
    for i, (cx, cy, half_w) in (frames_of_interest or {}).items():
        line, red, al, rgb = render(int(i))
        y0, y1 = max(0, cy - half_w // 2), min(h, cy + half_w // 2)
        x0, x1 = max(0, cx - half_w), min(w, cx + half_w)
        crop = lambda im: cv2.resize(im[y0:y1, x0:x1], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        alpha8 = cv2.cvtColor((al * 255).astype(np.uint8), cv2.COLOR_GRAY2RGB)
        top = np.hstack([crop(line), crop(alpha8)])
        cv2.imwrite(str(qd / f"qc_f{int(i):03d}_zoom.png"), cv2.cvtColor(top, cv2.COLOR_RGB2BGR))
        cv2.imwrite(str(qd / f"qc_f{int(i):03d}_full.png"),
                    cv2.cvtColor(np.vstack([line, red]), cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    ap.add_argument("stage", choices=["sam", "refine", "qc", "all"])
    a = ap.parse_args()
    cfg = config.load(a.shot)
    if a.stage in ("sam", "all"):
        run_sam(cfg)
    if a.stage in ("refine", "all"):
        run_refine(cfg)
    if a.stage in ("qc", "all"):
        run_qc(cfg, cfg.get("mattes", {}).get("qc_frames"))
