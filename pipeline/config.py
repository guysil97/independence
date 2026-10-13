"""Per-shot config loading, timecode helpers and work-dir layout."""
from __future__ import annotations

import json
from pathlib import Path

from . import media

ROOT = Path(__file__).resolve().parent.parent


def tc_to_frames(tc: str, fps: int) -> int:
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * fps + f


def frames_to_tc(n: int, fps: int) -> str:
    f = n % fps
    s = n // fps
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def load(shot: str) -> dict:
    cfg = json.loads((ROOT / "config" / f"{shot}.json").read_text())
    cfg["plate"] = str(ROOT / cfg["plate"])
    notes = ROOT / "notes" / f"{shot}.json"
    cfg["_notes"] = json.loads(notes.read_text()) if notes.exists() else {}
    cfg["_probe"] = media.probe(cfg["plate"])["summary"]
    p = cfg["_probe"]
    fps = round(p["fps"])
    cfg["_fps"] = fps
    rng = cfg.get("frame_range")
    if rng is None:
        first, last = 0, p["frames"] - 1
    else:
        first, last = (tc_to_frames(x, fps) - tc_to_frames(p["timecode"], fps) if isinstance(x, str) else x
                       for x in rng)
    cfg["_first"], cfg["_last"] = first, last
    cfg["_count"] = last - first + 1
    cfg["_start_tc"] = frames_to_tc(tc_to_frames(p["timecode"] or "00:00:00:00", fps) + first, fps)
    cfg["_work"] = ROOT / "work" / shot
    cfg["_regions_path"] = ROOT / cfg.get("regions", f"config/regions/{shot}.json")
    return cfg


def plate_tc(cfg: dict, plate_frame: int) -> str:
    fps = cfg["_fps"]
    return frames_to_tc(tc_to_frames(cfg["_probe"]["timecode"] or "00:00:00:00", fps) + plate_frame, fps)


def work(cfg: dict, *parts) -> Path:
    p = cfg["_work"].joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
