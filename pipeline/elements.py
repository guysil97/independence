"""Procedural elements, rendered in reference-frame coordinates (scene-linear).

* light_field(t): the street light behind the blinds — soft, desaturated coloured
  blobs from the props plus soft dark body occlusion. Low resolution (it is very
  soft); warped and upsampled to each frame by the compositor.
* door_bokeh(t): defocused LED props seen through the door glass, matched to the
  measured plate bokeh (size, anamorphic oval, edge softness), sized by distance
  from the focus plane, 180-degree shutter motion blur by sub-frame sampling.
* fireworks(t): rare broad flashes, fast attack / exponential decay.
"""
from __future__ import annotations

import numpy as np
import cv2

from . import crowd as cr


class Elements:
    def __init__(self, cfg: dict, pipe, shape, fps: float, duration_s: float):
        self.cfg, self.pipe, self.shape, self.fps = cfg, pipe, shape, fps
        e = cfg["elements"]
        self.e = e
        self.g = cfg["geometry"]
        self.passers = cr.build_crowd(cfg, duration_s, cfg["seed"])
        self.ls = int(e["light_field"]["downscale"])
        h, w = shape
        self.lh, self.lw = (h + self.ls - 1) // self.ls, (w + self.ls - 1) // self.ls
        self._yy, self._xx = np.mgrid[0:self.lh, 0:self.lw].astype(np.float32) * self.ls + self.ls / 2
        self._color_cache = {}
        self.fw = self._plan_fireworks(duration_s)

    # ---------------------------------------------------------------- helpers
    def px(self, x_m, h_m):
        g = self.g
        return x_m * g["px_per_m"] + g.get("x0_px", 0.0), g["y_ground_px"] - h_m * g["px_per_m"]

    def lin_color(self, rgb_disp, desat=0.0):
        key = (tuple(np.round(rgb_disp, 3)), round(desat, 3))
        if key not in self._color_cache:
            c = self.pipe.display709_to_working(np.asarray(rgb_disp, np.float64))
            y = float(self.pipe.luminance(c[None, :])[0])
            c = c / max(y, 1e-6)  # unit luminance
            c = (1 - desat) * c + desat * np.ones(3)
            self._color_cache[key] = c.astype(np.float32)
        return self._color_cache[key]

    def shutter_times(self, t, n):
        """n samples across a 180-degree shutter centred on t."""
        if n <= 1:
            return [t]
        half = 0.5 / self.fps / 2
        return list(np.linspace(t - half, t + half, n))

    # ---------------------------------------------------------------- blinds
    def light_field(self, t: float, scale: float = 1.0):
        """-> (L rgb [lh,lw,3], O [lh,lw]) relative units, reference coords, low res."""
        lf = self.e["light_field"]
        L = np.zeros((self.lh, self.lw, 3), np.float32)
        O = np.zeros((self.lh, self.lw), np.float32)
        ts = self.shutter_times(t, lf.get("shutter_samples", 3))
        ppm = self.g["px_per_m"]
        w_px = self.shape[1]
        for p in self.passers:
            x_now = float(p.x(t))
            xp_now, _ = self.px(x_now, 0)
            reach = (lf["sigma_base_m"] + lf["sigma_per_m"] * p.dist) * ppm * 3 + 200
            if xp_now < -reach or xp_now > w_px + reach:
                continue
            att = 1.0 / (1.0 + (p.dist / lf["falloff_m"]) ** 2)
            for ts_ in ts:
                # body occlusion: soft vertical shape, penumbra grows with distance
                xb, _ = self.px(float(p.x(ts_)), 0)
                _, ytop = self.px(0, p.height + float(p.bob(ts_)))
                _, ygnd = self.px(0, 0)
                sb = (lf["occl_blur_base_m"] + lf["occl_blur_per_m"] * p.dist) * ppm
                sx = np.hypot(p.width * ppm / 2.5, sb)
                gx = np.exp(-0.5 * ((self._xx[0] - xb) / sx) ** 2)
                gy = 1.0 / (1.0 + np.exp(-(self._yy[:, 0] - ytop) / max(sb * 0.6, 1)))
                gy *= 1.0 / (1.0 + np.exp((self._yy[:, 0] - ygnd) / max(sb * 0.6, 1)))
                s = lf["occl_max"] / (1.0 + (p.dist / lf["occl_falloff_m"]) ** 2)
                O += (s / len(ts)) * gy[:, None] * gx[None, :]
                for pr in p.props:
                    k = pr.intensity(ts_, for_area=True)
                    if k <= 0:
                        continue
                    xm, hm = cr.prop_position(p, pr, ts_)
                    xp, yp = self.px(xm, hm)
                    sig = (lf["sigma_base_m"] + lf["sigma_per_m"] * p.dist) * ppm
                    sx_, sy_ = sig * lf["aspect_x"], sig
                    gxp = np.exp(-0.5 * ((self._xx[0] - xp) / sx_) ** 2)
                    gyp = np.exp(-0.5 * ((self._yy[:, 0] - yp) / sy_) ** 2)
                    amp = pr.brightness * k * att / len(ts)
                    col = self.lin_color(pr.rgb(ts_), lf["desaturate"])
                    L += (amp * gyp[:, None] * gxp[None, :])[..., None] * col
        L *= lf["k_gain"] * scale
        cap = lf["cap"]
        L = cap * np.tanh(L / cap)  # bright props pressed against the glass saturate softly
        O = np.clip(O * scale, 0, lf["occl_max"])
        return L, O

    # ---------------------------------------------------------------- door
    def _sprite(self, minor, major, edge):
        """Anamorphic, centre-weighted defocus disc normalised to peak 1."""
        a, b = major / 2 + edge, minor / 2 + edge
        hh, hw = int(np.ceil(a)) + 2, int(np.ceil(b)) + 2
        yy, xx = np.mgrid[-hh:hh + 1, -hw:hw + 1].astype(np.float32)
        r = np.sqrt((xx / (minor / 2)) ** 2 + (yy / (major / 2)) ** 2)  # 1 at the nominal rim
        soft = edge / (minor / 2)
        rim = np.clip((1 + soft / 2 - r) / soft, 0, 1)
        rim = rim * rim * (3 - 2 * rim)
        bd = self.e["door_bokeh"]
        centre = 1 - (1 - bd["rim_to_core"]) * np.clip(r, 0, 1) ** 2  # measured rim/core ~0.79
        return (rim * centre).astype(np.float32)

    def door_bokeh(self, t: float, face_fn=None, scale: float = 1.0, blink_scale: float = 1.0):
        """-> RGB [h,w,3] additive light (working linear), reference coords."""
        bd = self.e["door_bokeh"]
        h, w = self.shape
        out = np.zeros((h, w, 3), np.float32)
        x0, y0, x1, y1 = bd["bbox_px"]
        ts = self.shutter_times(t, bd.get("shutter_samples", 5))
        f, dref = bd["focus_m"], bd["ref_dist_m"]
        coc_ref = abs(1 / f - 1 / dref)
        for p in self.passers:
            xp_now, _ = self.px(float(p.x(t)), 0)
            if xp_now < x0 - 200 or xp_now > x1 + 200:
                continue
            dobj = bd["glass_dist_m"] + p.dist
            sz = abs(1 / f - 1 / dobj) / coc_ref
            minor, major = bd["ref_minor_px"] * sz, bd["ref_major_px"] * sz
            edge = bd["ref_edge_px"] * sz
            spr = self._sprite(minor, major, edge)
            # energy conservation: a bigger disc of the same light is dimmer
            dim = 1.0 / (sz * sz) / (1.0 + (p.dist / bd["falloff_m"]) ** 2)
            for pr in p.props:
                for ts_ in ts:
                    k = pr.intensity(ts_)
                    if blink_scale < 1 and pr.fast:  # near faces: shallower blinking
                        k = (1 - blink_scale) * 0.45 + blink_scale * k
                    if k <= 0:
                        continue
                    xm, hm = cr.prop_position(p, pr, ts_)
                    xp, yp = self.px(xm, hm)
                    if not (x0 - 60 <= xp <= x1 + 60 and y0 - 80 <= yp <= y1 + 80):
                        continue
                    amp = min(bd["peak_lin"] * pr.brightness * k * dim, bd["max_peak_lin"]) * scale / len(ts)
                    col = self.lin_color(pr.rgb(ts_), bd.get("desaturate", 0.15))
                    sh, sw = spr.shape
                    cx, cy = int(round(xp)) - sw // 2, int(round(yp)) - sh // 2
                    ax0, ay0, ax1, ay1 = max(cx, 0), max(cy, 0), min(cx + sw, w), min(cy + sh, h)
                    if ax1 <= ax0 or ay1 <= ay0:
                        continue
                    s = spr[ay0 - cy:ay1 - cy, ax0 - cx:ax1 - cx]
                    out[ay0:ay1, ax0:ax1] += (amp * s)[..., None] * col
        return out

    def door_occlusion(self, t: float):
        """Very soft dark shapes of passers on the door glass, low res [lh,lw]."""
        bd = self.e["door_bokeh"]
        O = np.zeros((self.lh, self.lw), np.float32)
        ppm = self.g["px_per_m"]
        for p in self.passers:
            xb, _ = self.px(float(p.x(t)), 0)
            if xb < -400 or xb > self.shape[1] + 400:
                continue
            _, ytop = self.px(0, p.height)
            sb = (0.25 + 0.15 * p.dist) * ppm
            gx = np.exp(-0.5 * ((self._xx[0] - xb) / np.hypot(p.width * ppm / 2.5, sb)) ** 2)
            gy = 1.0 / (1.0 + np.exp(-(self._yy[:, 0] - ytop) / max(sb * 0.6, 1)))
            O += bd["occl_max"] / (1.0 + (p.dist / 1.5) ** 2) * gy[:, None] * gx[None, :]
        return np.clip(O, 0, bd["occl_max"])

    # ---------------------------------------------------------------- fireworks
    def _plan_fireworks(self, duration_s):
        fw = self.e["fireworks"]
        rng = np.random.default_rng(self.cfg["seed"] + 77)
        times = fw.get("at_s")
        if times is None:
            n = rng.integers(fw["count"][0], fw["count"][1] + 1)
            times = sorted(rng.uniform(0.5, max(duration_s - 1.0, 0.6), n).tolist())
        bursts = []
        for t0 in times:
            n = 1 + (rng.random() < fw["multi_burst_prob"]) + (rng.random() < fw["multi_burst_prob"] / 2)
            t = t0
            for j in range(n):
                col = fw["palette"][rng.integers(len(fw["palette"]))]
                pk = rng.uniform(*fw["peak"]) * (fw.get("follow_up_scale", 1.0) if j else 1.0)
                bursts.append({"t": t, "peak": pk, "decay": rng.uniform(*fw["decay_s"]),
                               "attack": rng.uniform(*fw["attack_frames"]) / self.fps, "color": col})
                t += rng.uniform(fw["min_burst_gap_s"], fw["min_burst_gap_s"] + 0.35)  # photosensitivity: <= ~2.5/s
        return bursts

    def fireworks(self, t: float, scale: float = 1.0):
        """-> rgb gain (3,) in working linear for the whole window area."""
        g = np.zeros(3, np.float32)
        for b in self.fw:
            dt = t - b["t"]
            if dt < -b["attack"] or dt > 6 * b["decay"]:
                continue
            env = (dt + b["attack"]) / b["attack"] if dt < 0 else np.exp(-dt / b["decay"])
            g += b["peak"] * env * self.lin_color(b["color"], self.e["fireworks"]["desaturate"])
        return g * scale
