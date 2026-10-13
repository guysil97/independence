# The Butcher Shop — off-screen Independence Day Eve, seen through the blinds

Procedural, seeded, config-driven window VFX for two shots. Actor pixels are
never touched; everything happens in scene-linear light inside the window
regions only.

## Layout

```
config/shot0X.json          per-shot settings (colour pipeline, crop, range, seed, analysis params)
config/regions/shot0X.json  editable polygons (windows, foreground objects, tracker exclusion)
notes/shot0X.json           optional: quiet ranges, fireworks times, global intensity
pipeline/                   python package (colorpipe, media, regions, motion, analyze, ...)
tests/                      unit tests (colour round-trip etc.)
plates/ work/ test/ out/    media — git-ignored, never committed
```

## Colour pipeline

`pipeline/colorpipe.py` is the only place transfer functions/gamuts live.

| plate | `color.input_transfer` | `color.input_gamut` | `crop` |
|---|---|---|---|
| look-dev proxies (graded Rec.709 H.264/HEVC) | `rec709_display` (BT.1886 γ2.4) | `rec709` | `{x:0,y:140,w:1920,h:800}` |
| real plates (Sony S-Log3 ProRes) | `slog3` | `sgamut3cine` | `null` |

`slog3_levels: "legal"` assumes a video-levels file decoded to full-range RGB by
ffmpeg (CV 95 = 0 % black, CV 420 = 18 % grey).

## Run

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTORCH_ENABLE_MPS_FALLBACK=1 OPENCV_IO_ENABLE_OPENEXR=1

python -m pytest -q tests
python -m pipeline.extract shot01    # probe + 16-bit TIFF / JPEG frames -> work/shot01/
python -m pipeline.analyze shot01    # regions, tracking, plate characterisation -> work/shot01/checkpoint1/
```
