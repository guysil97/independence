# QC — shot01 (test)

Comp: `test/shot01_comp_rec709_display.mov` · frames 0–74 (TC 01:00:23:04 – 01:00:26:03) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 11.79 · p99.9 4.17 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 11.49 · p99.9 4.17 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.338 % of window lum · max onsets/s 0 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 8-bit h264: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +1.23 %, min -1.04 %, max +3.92 %  ·  local change in visible window area (p95 per frame): median 45.6 %, max 284.5 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 0 | 01:00:23:04 | 8.62 | 3.61 |
| 5 | 01:00:23:09 | 7.59 | 3.43 |
| 10 | 01:00:23:14 | 7.41 | 3.67 |
| 15 | 01:00:23:19 | 9.19 | 3.75 |
| 20 | 01:00:23:24 | 8.04 | 3.92 |
| 25 | 01:00:24:04 | 9.43 | 4.07 |
| 30 | 01:00:24:09 | 11.49 | 4.17 |
| 35 | 01:00:24:14 | 10.35 | 3.72 |
| 40 | 01:00:24:19 | 8.76 | 3.95 |
| 45 | 01:00:24:24 | 7.41 | 3.59 |
| 50 | 01:00:25:04 | 5.34 | 2.75 |
| 55 | 01:00:25:09 | 5.00 | 2.90 |
| 60 | 01:00:25:14 | 5.76 | 2.87 |
| 65 | 01:00:25:19 | 5.40 | 2.86 |
| 70 | 01:00:25:24 | 5.48 | 2.89 |
| 74 | 01:00:26:03 | 4.78 | 2.86 |

Fireworks scheduled (s from start of working range): 
