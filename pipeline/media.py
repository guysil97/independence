"""ffprobe / ffmpeg I/O. Frames move as float32 RGB in [0, 1] (full-range R'G'B')."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np


def probe(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    tags = {**data["format"].get("tags", {})}
    for s in data["streams"]:
        tags.update({k: v_ for k, v_ in s.get("tags", {}).items() if k in ("timecode", "reel_name")})
    summary = {
        "file": str(path),
        "codec": v["codec_name"], "profile": v.get("profile"),
        "width": v["width"], "height": v["height"],
        "pix_fmt": v["pix_fmt"],
        "bit_depth": int(v.get("bits_per_raw_sample") or (10 if "10" in v["pix_fmt"] else 8)),
        "fps_num": num, "fps_den": den, "fps": num / den,
        "frames": int(v.get("nb_frames") or 0),
        "duration": float(data["format"]["duration"]),
        "color_range": v.get("color_range"), "color_space": v.get("color_space"),
        "color_transfer": v.get("color_transfer"), "color_primaries": v.get("color_primaries"),
        "timecode": tags.get("timecode"), "reel_name": tags.get("reel_name"),
    }
    return {"summary": summary, "raw": data}


def _yuv_to_rgb_filter(cfg: dict) -> str:
    c = cfg["color"]
    return (f"scale=in_color_matrix={c.get('yuv_matrix', 'bt709')}:in_range={c.get('range', 'tv')}"
            f":out_range=full:flags=accurate_rnd+full_chroma_int+bitexact+spline,format=rgb48le")


def read_frames(cfg: dict, start: int, count: int, crop=True):
    """Yield (plate_frame_index, float32 HxWx3) for `count` frames from `start`."""
    p = cfg["_probe"]
    w, h = p["width"], p["height"]
    vf = [f"trim=start_frame={start}:end_frame={start + count}", "setpts=PTS-STARTPTS",
          _yuv_to_rgb_filter(cfg)]
    cr = cfg.get("crop") if crop else None
    if cr:
        vf.append(f"crop={cr['w']}:{cr['h']}:{cr['x']}:{cr['y']}")
        w, h = cr["w"], cr["h"]
    cmd = ["ffmpeg", "-v", "error", "-i", str(cfg["plate"]), "-map", "0:v:0",
           "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    nbytes = w * h * 3 * 2
    i = 0
    try:
        while True:
            buf = proc.stdout.read(nbytes)
            if len(buf) < nbytes:
                break
            arr = np.frombuffer(buf, dtype="<u2").reshape(h, w, 3)
            yield start + i, arr.astype(np.float32) / 65535.0
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()
    if i != count:
        raise RuntimeError(f"expected {count} frames from {cfg['plate']}, got {i}")


def quantize16(img: np.ndarray, rng: np.random.Generator | None = None) -> np.ndarray:
    """float [0,1] -> uint16 with TPDF dither (1 LSB of 16-bit; we re-quantise to 10-bit later)."""
    x = np.clip(img, 0, 1) * 65535.0
    if rng is not None:
        x = x + (rng.random(x.shape, dtype=np.float32) - rng.random(x.shape, dtype=np.float32))
    return np.clip(np.rint(x), 0, 65535).astype(np.uint16)


def dither_to_10bit(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Dither float [0,1] to the 10-bit grid (TPDF, 1 LSB) and return float on that grid."""
    x = np.clip(img, 0, 1) * 1023.0
    x = x + (rng.random(x.shape, dtype=np.float32) - rng.random(x.shape, dtype=np.float32))
    return np.clip(np.rint(x), 0, 1023).astype(np.float32) / 1023.0


class ProResWriter:
    """Pipe float RGB frames into ffmpeg -> ProRes 4444 / 4444 XQ (10-bit 4:4:4)."""

    def __init__(self, path, cfg: dict, width: int, height: int, profile="4444",
                 timecode: str | None = None, reel: str | None = None):
        c = cfg["color"]
        prof = {"4444": "4", "4444xq": "5"}[profile.lower()]
        tags = []
        if c["input_transfer"] == "rec709_display":
            tags = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
        else:
            tags = ["-colorspace", "bt709"]  # matrix only; S-Log3 has no ffmpeg trc tag
        fps = f"{cfg['_probe']['fps_num']}/{cfg['_probe']['fps_den']}"
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le",
               "-s", f"{width}x{height}", "-r", fps, "-i", "-",
               "-vf", f"scale=out_color_matrix={c.get('yuv_matrix', 'bt709')}:in_range=full"
                      f":out_range={c.get('range', 'tv')}:flags=accurate_rnd+full_chroma_int+bitexact,"
                      f"format=yuv444p10le",
               "-c:v", "prores_ks", "-profile:v", prof, "-vendor", "apl0", "-pix_fmt", "yuv444p10le",
               *tags]
        if timecode:
            cmd += ["-timecode", timecode]
        if reel:
            cmd += ["-metadata:s:v:0", f"reel_name={reel}", "-metadata", f"reel_name={reel}"]
        cmd += [str(path)]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, img: np.ndarray):
        # img must already be on the 10-bit grid (dither_to_10bit) so ffmpeg's
        # 16->10 bit rounding is exact.
        self.proc.stdin.write(np.clip(np.rint(img * 65535.0), 0, 65535).astype("<u2").tobytes())

    def close(self):
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg ProRes encode failed")


class H264Writer:
    """Review-only H.264 (yuv420p, BT.709)."""

    def __init__(self, path, fps: str, width: int, height: int, crf=16):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", fps, "-i", "-",
               "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
               "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
               "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
               "-movflags", "+faststart", str(path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, img: np.ndarray):
        self.proc.stdin.write(np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8).tobytes())

    def close(self):
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg H.264 encode failed")
