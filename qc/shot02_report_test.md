# QC — shot02 (test)

Comp: `test/shot02_comp_rec709_display.mov` · frames 34–108 (TC 01:00:01:01 – 01:00:04:00) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 19.84 · p99.9 5.34 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 19.84 · p99.9 5.46 |
| region containment (diff outside windows) | FAIL | max 1.37e-03 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.455 % of window lum · max onsets/s 1 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 10-bit hevc: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +20.16 %, min +9.63 %, max +40.67 %  ·  local change in visible window area (p95 per frame): median 35.7 %, max 57.5 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 34 | 01:00:01:01 | 11.21 | 3.42 |
| 39 | 01:00:01:06 | 6.85 | 3.22 |
| 44 | 01:00:01:11 | 11.30 | 3.12 |
| 49 | 01:00:01:16 | 9.19 | 3.75 |
| 54 | 01:00:01:21 | 8.93 | 3.32 |
| 59 | 01:00:02:01 | 6.54 | 3.14 |
| 64 | 01:00:02:06 | 10.07 | 4.46 |
| 69 | 01:00:02:11 | 12.71 | 4.09 |
| 74 | 01:00:02:16 | 9.88 | 3.67 |
| 79 | 01:00:02:21 | 6.70 | 3.51 |
| 84 | 01:00:03:01 | 10.96 | 4.03 |
| 89 | 01:00:03:06 | 12.04 | 3.87 |
| 94 | 01:00:03:11 | 11.30 | 4.56 |
| 99 | 01:00:03:16 | 7.85 | 3.65 |
| 104 | 01:00:03:21 | 12.22 | 5.07 |
| 108 | 01:00:04:00 | 9.58 | 3.76 |

Fireworks scheduled (s from start of working range): 0.46, 0.86, 1.61, 2.74, 5.08, 5.75, 6.65
