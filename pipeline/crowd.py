"""Crowd model: the shared, seeded driver for every element.

Passers walk along the street parallel to the storefront. Positions are in metres
along the storefront axis (x = 0 at the left edge of the reference frame), height
above the pavement, and distance from the glass. `Street` converts to reference-
frame pixels with the per-shot `geometry` config.

Groups arrive as a clustered Poisson process with lulls; each person may carry
0-3 light props from the Independence Day Eve palette, each with its own blink
pattern and phase. Nothing is periodic or synchronised.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Prop:
    kind: str
    color: np.ndarray            # Rec.709 display RGB 0..1 (base colour)
    brightness: float            # relative emitted light (blue LED = 1)
    pattern: str                 # steady | slow_pulse | fast_strobe | chase | sparkle | color_cycle | phone
    rate_hz: float
    phase: float
    height_m: float
    dx_m: float                  # offset from the carrier's centre line
    swing_amp_m: float = 0.0     # hammers / swords swung in arcs
    swing_hz: float = 0.0
    on_window: tuple = (-1e9, 1e9)  # phone torches are only on for a while
    sparkle_seed: int = 0
    fast: bool = False           # fast blinkers: door bokeh only, time-averaged in the blinds

    def intensity(self, t: np.ndarray | float, for_area: bool = False):
        """Instantaneous emission multiplier in [0, 1]. for_area: low-passed version
        for large-area light (blinds), so nothing flickers across the window."""
        t = np.asarray(t, dtype=np.float64)
        on = ((t >= self.on_window[0]) & (t <= self.on_window[1])).astype(np.float64)
        p = self.pattern
        if p in ("steady", "color_cycle"):
            v = np.ones_like(t)
        elif p == "phone":
            # soft on/off edges (0.15 s) so a torch never pops
            a = np.clip((t - self.on_window[0]) / 0.15, 0, 1) * np.clip((self.on_window[1] - t) / 0.15, 0, 1)
            return a
        elif p == "slow_pulse":
            v = 0.55 + 0.45 * np.sin(2 * np.pi * (self.rate_hz * t + self.phase))
        elif p in ("fast_strobe", "chase", "sparkle"):
            if for_area:
                v = np.full_like(t, 0.45)  # duty-cycle mean: no large-area flicker
            elif p == "fast_strobe":
                v = (np.mod(self.rate_hz * t + self.phase, 1.0) < 0.4).astype(np.float64)
            elif p == "chase":
                v = 0.25 + 0.75 * np.clip(np.sin(2 * np.pi * (self.rate_hz * t + self.phase)), 0, 1) ** 2
            else:  # sparkle: random on-states held for 1/rate s, hashed from time
                k = np.floor(self.rate_hz * t + self.phase).astype(np.int64)
                h = (k * 2654435761 + self.sparkle_seed * 97531) % 1000003
                v = (h / 1000003.0 > 0.55).astype(np.float64)
        elif p == "none":
            return np.zeros_like(t)
        else:
            v = np.ones_like(t)
        return v * on

    def rgb(self, t: float) -> np.ndarray:
        if self.pattern != "color_cycle":
            return self.color
        hue = (self.phase + t * self.rate_hz) % 1.0
        return np.array(colorsys.hsv_to_rgb(hue, 0.85, 1.0))


@dataclass
class Passer:
    t0: float          # time the passer is at x_start
    x_start: float     # m
    v: float           # m/s, signed (+ = left to right in frame)
    dist: float        # m from the glass
    height: float      # body height m
    width: float       # shoulder width m
    gait_hz: float
    gait_amp: float
    gait_phase: float
    kid: bool
    props: list = field(default_factory=list)

    def x(self, t):
        return self.x_start + self.v * (np.asarray(t) - self.t0)

    def bob(self, t):
        return self.gait_amp * np.sin(2 * np.pi * (self.gait_hz * np.asarray(t) + self.gait_phase))


PALETTE = {
    # kind: (weight, colours (Rec.709 display), brightness, patterns, (h_min, h_max) above head-relative?)
    "blue_led":     (0.36, [(0.10, 0.32, 1.00), (0.15, 0.45, 1.00)], 1.0, ["steady", "slow_pulse", "chase"]),
    "white_led":    (0.24, [(0.82, 0.90, 1.00)], 1.2, ["steady", "slow_pulse"]),
    "hammer":       (0.12, None, 1.6, ["color_cycle"]),
    "flashing_toy": (0.12, [(1.0, 0.25, 0.30), (0.2, 0.5, 1.0), (1.0, 0.85, 0.3), (0.4, 1.0, 0.5)], 0.5,
                     ["fast_strobe", "sparkle", "chase"]),
    "glow_stick":   (0.12, [(0.35, 1.0, 0.45), (1.0, 0.35, 0.75), (0.25, 0.55, 1.0)], 0.4, ["steady"]),
    "phone":        (0.04, [(0.92, 0.96, 1.00)], 3.0, ["phone"]),
    # Yom Ha'atzmaut evening specifics
    "star_led":     (0.08, [(0.0, 0.22, 0.72), (0.15, 0.35, 1.0)], 1.1, ["steady", "slow_pulse"]),  # flag blue #0038B8
    "light_horns":  (0.06, [(1.0, 0.15, 0.25), (0.15, 0.35, 1.0)], 0.6, ["fast_strobe", "chase"]),
    "led_glasses":  (0.05, [(0.2, 0.45, 1.0), (0.9, 0.95, 1.0)], 0.5, ["chase", "sparkle"]),
    "flag":         (0.10, [(1.0, 1.0, 1.0)], 0.0, ["none"]),  # non-emissive: a waving shadow above the crowd
}


def build_crowd(cfg: dict, duration_s: float, seed: int) -> list[Passer]:
    c = cfg["crowd"]
    rng = np.random.default_rng(seed)
    g = cfg["geometry"]
    x_lo, x_hi = g["street_extent_m"]
    pal = {k: v for k, v in PALETTE.items() if c.get("palette_weights", {}).get(k, 1) > 0}
    weights = np.array([c.get("palette_weights", {}).get(k, pal[k][0]) for k in pal])
    weights /= weights.sum()
    kinds = list(pal)
    passers = []
    # the street is already busy when the shot starts: begin the process early
    t = -c.get("prewarm_s", 25.0)
    while t < duration_s + 2:
        n = rng.integers(c["group_size"][0], c["group_size"][1] + 1)
        direction = 1 if rng.random() < c.get("left_to_right_prob", 0.5) else -1  # parade: mostly one way
        group_dist = rng.uniform(*c["distance_m"])
        group_speed = rng.uniform(*c["walk_speed_mps"])
        for _ in range(n):
            kid = rng.random() < c["kid_prob"]
            v = (rng.uniform(*c["kid_speed_mps"]) if kid and rng.random() < 0.6 else
                 group_speed * rng.uniform(0.92, 1.08)) * direction
            dist = float(np.clip(group_dist + rng.normal(0, 0.4), c["distance_m"][0], c["distance_m"][1]))
            # enter from off-frame on the side they come from; stagger within the group
            x_start = (x_lo if direction > 0 else x_hi) - direction * rng.uniform(0, 1.8)
            p = Passer(t0=t + rng.uniform(0, 1.5), x_start=x_start, v=v, dist=dist,
                       height=rng.uniform(1.15, 1.35) if kid else rng.uniform(1.6, 1.9),
                       width=0.32 if kid else rng.uniform(0.42, 0.52),
                       gait_hz=(2.6 if kid else c["gait_hz"]) * rng.uniform(0.9, 1.1),
                       gait_amp=c["gait_amp_m"] * rng.uniform(0.7, 1.3), gait_phase=rng.random(), kid=kid)
            for _ in range(rng.integers(c["props_per_person"][0], c["props_per_person"][1] + 1)):
                k = kinds[rng.choice(len(kinds), p=weights)]
                _, cols, bright, pats = pal[k]
                pat = pats[rng.integers(len(pats))]
                col = np.array(cols[rng.integers(len(cols))] if cols else (1, 1, 1), np.float64)
                if k == "flag":  # pole flag waved above the heads
                    h, rate, amp, shz = p.height + rng.uniform(0.5, 1.0), rng.uniform(0.6, 1.4), \
                        rng.uniform(0.15, 0.35), rng.uniform(0.3, 0.7)
                elif k in ("light_horns", "led_glasses"):  # worn on the head
                    h, rate, amp, shz = p.height - rng.uniform(0.05, 0.15), rng.uniform(4, 9), 0, 0
                elif k == "hammer":
                    h, rate, amp, shz = rng.uniform(0.9, 1.5) * p.height / 1.75, 1 / rng.uniform(1, 3), \
                        rng.uniform(0.15, 0.35), rng.uniform(0.4, 0.9)
                elif k == "phone":
                    h, rate, amp, shz = rng.uniform(1.1, 1.5) * p.height / 1.75, 0, 0, 0
                elif k == "flashing_toy" and rng.random() < 0.5:  # headband
                    h, rate, amp, shz = p.height - 0.08, rng.uniform(4, 10), 0, 0
                else:
                    h, rate, amp, shz = rng.uniform(0.7, 1.3) * p.height / 1.75, \
                        (rng.uniform(4, 10) if pat in ("fast_strobe", "sparkle", "chase") else rng.uniform(0.4, 1.2)), \
                        rng.uniform(0.02, 0.08), rng.uniform(0.8, 1.2) * p.gait_hz / 2
                on = (-1e9, 1e9)
                if k == "phone":
                    t_on = p.t0 + rng.uniform(0, 4)
                    on = (t_on, t_on + rng.uniform(0.8, 3.0))
                p.props.append(Prop(kind=k, color=col, brightness=bright * rng.uniform(0.7, 1.3), pattern=pat,
                                    rate_hz=rate, phase=rng.random(), height_m=h, dx_m=rng.uniform(-0.25, 0.25),
                                    swing_amp_m=amp, swing_hz=shz, on_window=on,
                                    sparkle_seed=int(rng.integers(1 << 30)),
                                    fast=pat in ("fast_strobe", "sparkle", "chase")))
            passers.append(p)
        # next group: clustered arrivals, occasional lulls
        gap = rng.uniform(*c["group_interarrival_s"])
        if rng.random() < c["lull_prob"]:
            gap += rng.uniform(*c["lull_s"])
        t += gap
    return passers


def prop_position(p: Passer, pr: Prop, t: float):
    """(x_m, h_m) of a prop at time t (carrier position + swing + gait)."""
    x = p.x(t) + pr.dx_m + pr.swing_amp_m * np.sin(2 * np.pi * (pr.swing_hz * t + pr.phase))
    h = pr.height_m + p.bob(t) + 0.5 * pr.swing_amp_m * np.cos(2 * np.pi * (pr.swing_hz * t + pr.phase))
    return float(x), float(h)
