# QC — shot02 (test)

Comp: `test/shot02_comp_rec709_display.mov` · frames 34–108 (TC 01:00:01:01 – 01:00:04:00) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 19.37 · p99.9 5.53 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 19.84 · p99.9 5.46 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.450 % of window lum · max onsets/s 1 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 10-bit hevc: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +19.94 %, min +9.34 %, max +40.40 %  ·  local change in visible window area (p95 per frame): median 35.8 %, max 57.5 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 34 | 01:00:01:01 | 11.21 | 3.42 |
| 39 | 01:00:01:06 | 9.93 | 3.28 |
| 44 | 01:00:01:11 | 11.30 | 3.22 |
| 49 | 01:00:01:16 | 9.19 | 3.76 |
| 54 | 01:00:01:21 | 8.93 | 3.32 |
| 59 | 01:00:02:01 | 6.54 | 3.14 |
| 64 | 01:00:02:06 | 9.41 | 4.37 |
| 69 | 01:00:02:11 | 12.71 | 4.04 |
| 74 | 01:00:02:16 | 6.88 | 3.62 |
| 79 | 01:00:02:21 | 6.70 | 3.51 |
| 84 | 01:00:03:01 | 10.96 | 3.73 |
| 89 | 01:00:03:06 | 10.71 | 3.81 |
| 94 | 01:00:03:11 | 11.30 | 4.50 |
| 99 | 01:00:03:16 | 8.12 | 3.72 |
| 104 | 01:00:03:21 | 9.52 | 4.95 |
| 108 | 01:00:04:00 | 9.58 | 3.76 |

Fireworks scheduled (s from start of working range): 0.46, 0.86, 1.61, 2.74, 5.08, 5.75, 6.65
