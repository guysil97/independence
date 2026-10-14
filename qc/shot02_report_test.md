# QC — shot02 (test)

Comp: `test/shot02_comp_rec709_display.mov` · frames 34–108 (TC 01:00:01:01 – 01:00:04:00) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 16.45 · p99.9 5.26 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 19.84 · p99.9 5.42 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.445 % of window lum · max onsets/s 1 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 10-bit hevc: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +19.72 %, min +9.06 %, max +40.07 %  ·  local change in visible window area (p95 per frame): median 35.9 %, max 57.5 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 34 | 01:00:01:01 | 11.21 | 3.39 |
| 39 | 01:00:01:06 | 9.93 | 3.11 |
| 44 | 01:00:01:11 | 11.30 | 3.06 |
| 49 | 01:00:01:16 | 8.93 | 3.73 |
| 54 | 01:00:01:21 | 8.93 | 3.26 |
| 59 | 01:00:02:01 | 6.54 | 3.12 |
| 64 | 01:00:02:06 | 9.41 | 4.32 |
| 69 | 01:00:02:11 | 12.71 | 4.04 |
| 74 | 01:00:02:16 | 6.88 | 3.62 |
| 79 | 01:00:02:21 | 6.63 | 3.53 |
| 84 | 01:00:03:01 | 8.69 | 4.06 |
| 89 | 01:00:03:06 | 10.71 | 3.81 |
| 94 | 01:00:03:11 | 11.30 | 4.96 |
| 99 | 01:00:03:16 | 8.12 | 3.67 |
| 104 | 01:00:03:21 | 10.02 | 4.89 |
| 108 | 01:00:04:00 | 9.58 | 3.75 |

Fireworks scheduled (s from start of working range): 0.46, 0.86, 1.61, 2.74, 5.08, 5.75, 6.65
