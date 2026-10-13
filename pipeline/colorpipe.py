"""Colour pipeline: plate code values <-> scene-linear working space.

Everything colour-related goes through this module, so switching from the
Rec.709 look-dev proxies to the real S-Log3 / S-Gamut3.Cine plates is a config
change only:

    "color": {"input_transfer": "rec709_display" | "slog3",
              "input_gamut":    "rec709"         | "sgamut3cine", ...}

Conventions
-----------
* `code` arrays are float32 R'G'B' in [0, 1] as delivered by `media.read_frames`,
  i.e. full-range normalised RGB after ffmpeg's YCbCr->RGB conversion
  (legal-range video 64..940 maps to 0..1).
* `linear` arrays are scene-linear (or, for the display-referred proxies,
  display-linear) RGB in the plate's own gamut. All compositing happens here.
* Colours specified in the configs are Rec.709 display-referred sRGB-ish
  triplets (0..1); `display709_to_working` converts them to working linear.
"""
from __future__ import annotations

import numpy as np

# --- Sony S-Log3 (Sony technical summary, S-Log3 / S-Gamut3.Cine) ------------
# `t` is the 10-bit code value / 1023 of the *legal-range* recorded signal.
_SL3_CUT_CV = 171.2102946929
_SL3_LIN_CUT = 0.01125000


def slog3_decode(t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, dtype=np.float64)
    cv = t * 1023.0
    hi = np.power(10.0, (cv - 420.0) / 261.5) * (0.18 + 0.01) - 0.01
    lo = (cv - 95.0) * _SL3_LIN_CUT / (_SL3_CUT_CV - 95.0)
    return np.where(cv >= _SL3_CUT_CV, hi, lo)


def slog3_encode(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    hi = (420.0 + np.log10(np.maximum(x + 0.01, 1e-12) / (0.18 + 0.01)) * 261.5) / 1023.0
    lo = (x * (_SL3_CUT_CV - 95.0) / _SL3_LIN_CUT + 95.0) / 1023.0
    return np.where(x >= _SL3_LIN_CUT, hi, lo)


# legal <-> full range for 10-bit video levels (Y 64..940)
def full_to_legal(v):
    return (np.asarray(v, dtype=np.float64) * 876.0 + 64.0) / 1023.0


def legal_to_full(t):
    return (np.asarray(t, dtype=np.float64) * 1023.0 - 64.0) / 876.0


# --- Rec.709 display (BT.1886, Lb = 0 -> pure power) --------------------------
def bt1886_decode(v, gamma=2.4):
    v = np.asarray(v, dtype=np.float64)
    return np.sign(v) * np.power(np.abs(v), gamma)


def bt1886_encode(x, gamma=2.4):
    x = np.asarray(x, dtype=np.float64)
    return np.sign(x) * np.power(np.abs(x), 1.0 / gamma)


# --- gamuts --------------------------------------------------------------------
def _gamut_matrix(src: str, dst: str) -> np.ndarray:
    if src == dst:
        return np.eye(3)
    import colour

    names = {"rec709": "ITU-R BT.709", "sgamut3cine": "S-Gamut3.Cine"}
    s = colour.RGB_COLOURSPACES[names[src]]
    d = colour.RGB_COLOURSPACES[names[dst]]
    return colour.matrix_RGB_to_RGB(s, d, chromatic_adaptation_transform="CAT02")


class ColorPipe:
    """Bidirectional plate <-> working-linear transform built from a config."""

    def __init__(self, cfg: dict):
        c = cfg["color"]
        self.transfer = c["input_transfer"]
        self.gamut = c.get("input_gamut", "rec709")
        self.gamma = float(c.get("display_gamma", 2.4))
        # how the S-Log3 code values sit in the decoded RGB: "legal" = the
        # camera's video-levels file decoded to full-range RGB by ffmpeg
        self.slog3_levels = c.get("slog3_levels", "legal")
        if self.transfer not in ("rec709_display", "slog3"):
            raise ValueError(f"unknown input_transfer {self.transfer!r}")
        self._m_709_to_work = _gamut_matrix("rec709", self.gamut).astype(np.float32)
        self._m_work_to_709 = _gamut_matrix(self.gamut, "rec709").astype(np.float32)

    # plate code values -> working linear
    def to_linear(self, code: np.ndarray) -> np.ndarray:
        if self.transfer == "rec709_display":
            out = bt1886_decode(code, self.gamma)
        else:
            t = full_to_legal(code) if self.slog3_levels == "legal" else code
            out = slog3_decode(t)
        return out.astype(np.float32)

    def from_linear(self, lin: np.ndarray) -> np.ndarray:
        if self.transfer == "rec709_display":
            out = bt1886_encode(lin, self.gamma)
        else:
            t = slog3_encode(lin)
            out = legal_to_full(t) if self.slog3_levels == "legal" else t
        return out.astype(np.float32)

    # config colours (Rec.709 display, 0..1) -> working linear gamut
    def display709_to_working(self, rgb) -> np.ndarray:
        lin709 = bt1886_decode(np.asarray(rgb, dtype=np.float64), 2.4)
        return (lin709 @ self._m_709_to_work.T).astype(np.float32)

    def luminance(self, lin: np.ndarray) -> np.ndarray:
        """Rec.709 luminance Y of a working-linear image (gamut-converted first)."""
        w = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32) @ self._m_work_to_709
        return lin @ w

    def preview_709(self, code: np.ndarray, lut=None) -> np.ndarray:
        """Display-referred Rec.709 preview (0..1) from plate code values."""
        if self.transfer == "rec709_display":
            return np.clip(code, 0, 1)
        if lut is not None:
            return lut.apply(code)
        # fallback S-Log3 -> 709: gamut matrix + simple filmic curve, review only
        lin = self.to_linear(code) @ self._m_work_to_709.T
        lin = np.maximum(lin, 0) * 1.8
        tm = lin / (1.0 + lin)
        return np.clip(bt1886_encode(tm, 2.4), 0, 1).astype(np.float32)
