"""Step 1.1–1.2: probe the plate, extract the working range to 16-bit TIFF + JPEG."""
from __future__ import annotations

import argparse
import json

import cv2
import numpy as np
import tifffile

from . import config, media


def run(shot: str):
    cfg = config.load(shot)
    pr = media.probe(cfg["plate"])
    out = config.work(cfg)
    summary = dict(pr["summary"], work_first_frame=cfg["_first"], work_last_frame=cfg["_last"],
                   work_frames=cfg["_count"], work_start_tc=cfg["_start_tc"],
                   work_end_tc=config.plate_tc(cfg, cfg["_last"]), crop=cfg.get("crop"))
    (out / "probe.json").write_text(json.dumps({"summary": summary, "raw": pr["raw"]}, indent=2))
    fr, jp = config.work(cfg, "frames"), config.work(cfg, "jpg")
    for n, img in media.read_frames(cfg, cfg["_first"], cfg["_count"]):
        i = n - cfg["_first"]
        tifffile.imwrite(fr / f"{i:05d}.tif", np.rint(img * 65535).astype(np.uint16))
        cv2.imwrite(str(jp / f"{i:05d}.jpg"), cv2.cvtColor(np.rint(img * 255).astype(np.uint8), cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    run(ap.parse_args().shot)
