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
        self.floats = self._plan_floats(duration_s)
        self.foam = self._plan_foam(duration_s)
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
                s = lf["occl_max"] / (1.0 + (p.dist / lf["occl_falloff_m"]) ** 2)
                if p.dist > lf.get("occl_max_dist_m", 1e9):
                    s = 0.0  # too far from the glass to cast a readable shadow on the blinds
                if s > 0 and lf.get("silhouette_shape", False):
                    O += (s / len(ts)) * self._silhouette(xb, ytop, ygnd, p.width * ppm, sb, ppm)
                elif s > 0:
                    sx = np.hypot(p.width * ppm / 2.5, sb)
                    gx = np.exp(-0.5 * ((self._xx[0] - xb) / sx) ** 2)
                    gy = 1.0 / (1.0 + np.exp(-(self._yy[:, 0] - ytop) / max(sb * 0.6, 1)))
                    gy *= 1.0 / (1.0 + np.exp((self._yy[:, 0] - ygnd) / max(sb * 0.6, 1)))
                    O += (s / len(ts)) * gy[:, None] * gx[None, :]
                for pr in p.props:
                    if pr.kind == "flag" and s <= 0:
                        continue
                    if pr.kind == "flag":  # pole flag: a fluttering soft shadow above the heads
                        xm, hm = cr.prop_position(p, pr, ts_)
                        xf, yf_top = self.px(xm + 0.45, hm)
                        _, yf_bot = self.px(0, hm - 0.75)
                        flutter = 0.65 + 0.35 * np.sin(2 * np.pi * (pr.rate_hz * ts_ + pr.phase))
                        sf = (lf["occl_blur_base_m"] + lf["occl_blur_per_m"] * p.dist) * ppm
                        gxf = np.exp(-0.5 * ((self._xx[0] - xf) / np.hypot(0.4 * ppm, sf)) ** 2)  # fixed width: no harmonics
                        gyf = (1.0 / (1.0 + np.exp(-(self._yy[:, 0] - yf_top) / max(sf * 0.6, 1)))) * \
                              (1.0 / (1.0 + np.exp((self._yy[:, 0] - yf_bot) / max(sf * 0.6, 1))))
                        O += (lf.get("flag_occl", 0.5) * s * flutter / len(ts)) * gyf[:, None] * gxf[None, :]
                        continue
                    # small point lights may blink (small area); broad glows are time-averaged
                    k = pr.intensity(ts_, for_area=not lf.get("small_lights_blink", False))
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
        L *= lf["k_gain"]
        L += self._floats_light(t)
        L += self._foam_light(t)
        sg = self.e.get("street_glow", {})
        if sg.get("gain", 0) > 0:  # the whole street is lit by the parade: a broad blue-white lift
            mod = 1 + sg.get("breath", 0.0) * np.sin(2 * np.pi * t / sg.get("breath_s", 7.0))
            L += sg["gain"] * mod * self.lin_color(sg["color"], sg.get("desaturate", 0.4))
        L *= scale
        cap = lf["cap"]
        L = cap * np.tanh(L / cap)  # bright props pressed against the glass saturate softly
        O = np.clip(O * scale, 0, lf["occl_max"])
        return L, O

    def _silhouette(self, xb, ytop, ygnd, w_px, blur, ppm):
        """Soft head-and-shoulders figure (low-res grid) whose edge softness grows with distance."""
        b = max(blur, 1.0)
        sig = lambda d: 1.0 / (1.0 + np.exp(np.clip(-d / (0.45 * b), -60, 60)))  # inside-positive soft step
        hr = 0.11 * ppm
        hcy = ytop + 1.15 * hr
        shoulder = ytop + 2.3 * hr
        x, y = self._xx, self._yy
        # torso narrows slightly towards the legs
        half = w_px / 2 * (1 - 0.25 * np.clip((y - shoulder) / max(ygnd - shoulder, 1), 0, 1))
        torso = sig(half - np.abs(x - xb)) * sig(y - shoulder) * sig(ygnd - y)
        r = np.sqrt(((x - xb) / hr) ** 2 + ((y - hcy) / (1.2 * hr)) ** 2)
        head = sig((1 - r) * hr)
        neck = sig(0.45 * hr - np.abs(x - xb)) * sig(y - (hcy + hr)) * sig(shoulder + 2 - y)
        return np.maximum(np.maximum(torso, head), neck).astype(np.float32)

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
        fc = self.e.get("floats", {})
        for fl in self.floats:
            dobj = bd["glass_dist_m"] + fl["dist"]
            sz = abs(1 / f - 1 / dobj) / coc_ref
            spr = self._sprite(bd["ref_minor_px"] * sz, bd["ref_major_px"] * sz, bd["ref_edge_px"] * sz)
            dim = 1.0 / (sz * sz) / (1.0 + (fl["dist"] / bd["falloff_m"]) ** 2)
            sh, sw = spr.shape
            for led in fl["leds"]:
                for ts_ in ts:
                    xm = self._float_x(fl, ts_) + led["dx"] * fl["len"]
                    xp, yp = self.px(xm, led["h"])
                    if not (x0 - 60 <= xp <= x1 + 60 and y0 - 80 <= yp <= y1 + 80):
                        continue
                    pat = led["pattern"]
                    k = 1.0 if pat == "steady" else (0.55 + 0.45 * np.sin(2 * np.pi * (0.8 * ts_ + led["phase"]))
                                                     if pat == "slow_pulse" else
                                                     0.25 + 0.75 * max(np.sin(2 * np.pi * (3 * ts_ + led["phase"])), 0) ** 2)
                    amp = min(bd["peak_lin"] * fc.get("led_brightness", 2.0) * k * dim, bd["max_peak_lin"]) * scale / len(ts)
                    col = self.lin_color(led["col"], bd.get("desaturate", 0.15))
                    cx, cy = int(round(xp)) - sw // 2, int(round(yp)) - sh // 2
                    ax0, ay0, ax1, ay1 = max(cx, 0), max(cy, 0), min(cx + sw, w), min(cy + sh, h)
                    if ax1 <= ax0 or ay1 <= ay0:
                        continue
                    out[ay0:ay1, ax0:ax1] += (amp * spr[ay0 - cy:ay1 - cy, ax0 - cx:ax1 - cx])[..., None] * col
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

    # ---------------------------------------------------------------- parade floats
    def _plan_floats(self, duration_s):
        fc = self.e.get("floats", {})
        if not fc.get("enabled", False):
            return []
        rng = np.random.default_rng(self.cfg["seed"] + 991)
        x_lo, x_hi = self.g["street_extent_m"]
        times = fc.get("at_s")
        if times is None:
            times = sorted(rng.uniform(-4, duration_s, rng.integers(fc["count"][0], fc["count"][1] + 1)).tolist())
        floats = []
        for t_mid in times:
            d = 1 if rng.random() < self.cfg["crowd"].get("left_to_right_prob", 0.5) else -1
            v = rng.uniform(*fc["speed_mps"]) * d
            x_mid = (x_lo + x_hi) / 2 + rng.uniform(-1, 1)  # centred in front of the windows at t_mid
            beams = [{"phase": rng.random(), "hz": rng.uniform(*fc["beam_sweep_hz"]),
                      "amp": np.radians(rng.uniform(*fc["beam_sweep_deg"])), "off": rng.uniform(-0.6, 0.6),
                      "col": fc["beam_colors"][rng.integers(len(fc["beam_colors"]))],
                      "dx": rng.uniform(-0.4, 0.4)} for _ in range(fc["beams"])]
            leds = [{"dx": rng.uniform(-0.5, 0.5), "h": rng.uniform(0.4, 3.2), "phase": rng.random(),
                     "col": fc["led_colors"][rng.integers(len(fc["led_colors"]))],
                     "pattern": ["steady", "chase", "slow_pulse"][rng.integers(3)]} for _ in range(fc["leds"])]
            floats.append({"t": t_mid, "x": x_mid, "v": v, "len": rng.uniform(*fc["length_m"]),
                           "dist": rng.uniform(*fc["dist_m"]), "wash_phase": rng.random(),
                           "wash_s": rng.uniform(*fc["wash_cycle_s"]), "beams": beams, "leds": leds})
        return floats

    def _float_x(self, f, t):
        return f["x"] + f["v"] * (t - f["t"])

    def _floats_light(self, t):
        fc = self.e.get("floats", {})
        L = np.zeros((self.lh, self.lw, 3), np.float32)
        if not self.floats:
            return L
        ppm = self.g["px_per_m"]
        for f in self.floats:
            xc = self._float_x(f, t)
            xp, yp = self.px(xc, fc["wash_height_m"])
            att = 1.0 / (1.0 + (f["dist"] / fc["falloff_m"]) ** 2)
            # colour wash cycling through the blue/white palette, very wide and soft
            cols = fc["wash_colors"]
            ph = (t / f["wash_s"] + f["wash_phase"]) % 1.0 * len(cols)
            a, b, fr = int(ph) % len(cols), (int(ph) + 1) % len(cols), ph - int(ph)
            col = (1 - fr) * self.lin_color(cols[a], fc["desaturate"]) + fr * self.lin_color(cols[b], fc["desaturate"])
            sx = (f["len"] / 2.2 + 0.6 * f["dist"]) * ppm
            sy = (1.2 + 0.3 * f["dist"]) * ppm
            g = np.exp(-0.5 * ((self._xx[0] - xp) / sx) ** 2)[None, :] * np.exp(-0.5 * ((self._yy[:, 0] - yp) / sy) ** 2)[:, None]
            L += (fc["wash_gain"] * att * g)[..., None] * col
            # moving-head beams: where a sweeping beam crosses the storefront, a soft bright band
            for bm in f["beams"]:
                ang = bm["off"] + bm["amp"] * np.sin(2 * np.pi * (bm["hz"] * t + bm["phase"]))
                x_hit = xc + bm["dx"] + f["dist"] * np.tan(ang)
                xh, _ = self.px(x_hit, 0)
                width = (fc["beam_width_m"] + 0.12 * f["dist"]) * ppm
                face_on = np.cos(ang) ** 3  # strongest when the head points straight at the window
                gb = np.exp(-0.5 * ((self._xx[0] - xh) / width) ** 2)
                yfall = np.clip(1 - (self._yy[:, 0] / self.shape[0]) * 0.4, 0.4, 1)  # beams come from above
                L += (fc["beam_gain"] * att * face_on * yfall[:, None] * gb[None, :])[..., None] * \
                    self.lin_color(bm["col"], fc["desaturate"])
        return L

    # ---------------------------------------------------------------- snow-spray foam
    def _plan_foam(self, duration_s):
        fo = self.e.get("foam", {})
        if not fo.get("enabled", False):
            return []
        rng = np.random.default_rng(self.cfg["seed"] + 4242)
        x_lo, x_hi = self.g["street_extent_m"]
        n = rng.poisson(fo["rate_per_s"] * (duration_s + 2))
        return [{"t": rng.uniform(-1, duration_s + 1), "x": rng.uniform(x_lo + 2, x_hi - 2),
                 "h": rng.uniform(*fo["height_m"]), "size": rng.uniform(*fo["size_m"]),
                 "life": rng.uniform(*fo["life_s"]), "dist": rng.uniform(*fo["dist_m"])} for _ in range(n)]

    def _foam_light(self, t):
        fo = self.e.get("foam", {})
        L = np.zeros((self.lh, self.lw, 3), np.float32)
        ppm = self.g["px_per_m"]
        white = self.lin_color((1, 1, 1), 0)
        for f in self.foam:
            u = (t - f["t"]) / f["life"]
            if not 0 <= u <= 1:
                continue
            env = np.sin(np.pi * u) ** 2  # puff appears and dissolves, catching the street light
            xp, yp = self.px(f["x"] + 0.3 * u, f["h"] - 0.3 * u)
            sig = (f["size"] * (0.6 + 0.6 * u) + 0.2 * f["dist"]) * ppm
            g = np.exp(-0.5 * (((self._xx - xp) / sig) ** 2 + ((self._yy - yp) / (0.8 * sig)) ** 2))
            L += (fo["gain"] * env / (1 + (f["dist"] / 1.5) ** 2) * g)[..., None] * white
        return L

    # ---------------------------------------------------------------- fireworks
    def _plan_fireworks(self, duration_s):
        fw = self.e["fireworks"]
        rng = np.random.default_rng(self.cfg["seed"] + 77)
        times = fw.get("at_s")
        if times is None and fw.get("show_rate_per_s", 0) > 0:  # municipal show: bursts all through the shot
            times, t = [], rng.exponential(1 / fw["show_rate_per_s"]) - 0.5
            while t < duration_s:
                times.append(t)
                t += max(rng.exponential(1 / fw["show_rate_per_s"]), fw["min_burst_gap_s"])
        elif times is None:
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
        bursts.sort(key=lambda b: b["t"])
        kept = []
        for b in bursts:  # photosensitivity: broad flashes never closer than min_burst_gap_s
            if not kept or b["t"] - kept[-1]["t"] >= fw["min_burst_gap_s"]:
                kept.append(b)
        return kept

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
