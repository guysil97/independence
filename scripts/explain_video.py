"""Labelled review video: before on top, after below, with Hebrew callouts.

    python scripts/explain_video.py shot01
Reads test/<shot>_preview_709.mp4 (before | after side by side) and writes
test/<shot>_review_he.mp4 plus a still test/<shot>_review_he.jpg.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# callouts in the 1920x800 active-area coordinates: (text, arrow tip x, y, label x, y)
CALLOUTS = {
    "shot01": [
        ("תריסים: אור כחול-לבן וצללים של קהל עוברים", (820, 260), (40, 40)),
        ("דלת זכוכית: רחוב מואר, אורות לד מטושטשים ודמויות", (1500, 560), (1000, 40)),
    ],
    "shot02": [
        ("תריסים: אור מהתהלוכה וצללים של עוברים ושבים", (900, 300), (40, 40)),
        ("תריסים: אור משאית התהלוכה והזיקוקים", (1830, 250), (1050, 40)),
    ],
}


def he(s):
    return s  # Pillow's raqm layout already handles right-to-left text


def main(shot):
    src = ROOT / "test" / f"{shot}_preview_709.mp4"
    out = ROOT / "test" / f"{shot}_review_he.mp4"
    W, H = 3840, 1080
    y0, ah = 140, 800  # active area inside the letterbox
    scale = 0.6667
    tw, th = int(1920 * scale), int(ah * scale)
    bar = 56
    OW, OH = tw, 2 * (th + bar)
    f_big, f_small = ImageFont.truetype(FONT_B, 30), ImageFont.truetype(FONT, 22)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}",
                            "-r", "25", "-i", "-", "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    n = 0
    still = None
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        before = Image.fromarray(fr[y0:y0 + ah, :1920]).resize((tw, th), Image.LANCZOS)
        after = Image.fromarray(fr[y0:y0 + ah, 1920:]).resize((tw, th), Image.LANCZOS)
        canvas = Image.new("RGB", (OW, OH), (18, 18, 18))
        d = ImageDraw.Draw(canvas)
        d.text((OW - 20, 12), he("לפני – הצילום המקורי"), font=f_big, fill=(230, 230, 230), anchor="ra")
        canvas.paste(before, (0, bar))
        d.text((OW - 20, th + bar + 12), he("אחרי – עם החגיגה ברחוב (רק בחלונות, השחקנים לא נגעו)"),
               font=f_big, fill=(255, 210, 90), anchor="ra")
        canvas.paste(after, (0, 2 * bar + th))
        ay = 2 * bar + th
        for text, (tx, ty), (lx, ly) in CALLOUTS.get(shot, []):
            tip = (int(tx * scale), ay + int(ty * scale))
            lab = (int(lx * scale), ay + int(ly * scale))
            bb = d.textbbox(lab, he(text), font=f_small)
            d.rectangle([bb[0] - 6, bb[1] - 4, bb[2] + 6, bb[3] + 4], fill=(0, 0, 0))
            d.text(lab, he(text), font=f_small, fill=(255, 255, 255))
            d.line([((bb[0] + bb[2]) // 2, bb[3] + 4), tip], fill=(255, 210, 90), width=3)
            d.ellipse([tip[0] - 6, tip[1] - 6, tip[0] + 6, tip[1] + 6], outline=(255, 210, 90), width=3)
        arr = np.asarray(canvas)
        enc.stdin.write(arr.tobytes())
        if n == 45:
            still = canvas
        n += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    (still or canvas).save(ROOT / "test" / f"{shot}_review_he.jpg", quality=92)
    print(out, n, "frames")


if __name__ == "__main__":
    main(sys.argv[1])
