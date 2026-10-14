# QC — shot02 (test)

Comp: `test/shot02_comp_rec709_display.mov` · frames 34–108 (TC 01:00:01:01 – 01:00:04:00) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 19.84 · p99.9 5.49 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 19.84 · p99.9 5.46 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | FAIL | >3 Hz rms 0.690 % of window lum · max onsets/s 1 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 10-bit hevc: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +20.78 %, min +6.98 %, max +42.48 %  ·  local change in visible window area (p95 per frame): median 34.4 %, max 63.4 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 34 | 01:00:01:01 | 11.21 | 3.61 |
| 39 | 01:00:01:06 | 9.93 | 3.47 |
| 44 | 01:00:01:11 | 11.13 | 3.45 |
| 49 | 01:00:01:16 | 10.80 | 4.09 |
| 54 | 01:00:01:21 | 9.10 | 3.76 |
| 59 | 01:00:02:01 | 9.88 | 3.42 |
| 64 | 01:00:02:06 | 15.67 | 4.07 |
| 69 | 01:00:02:11 | 9.24 | 4.17 |
| 74 | 01:00:02:16 | 18.98 | 4.12 |
| 79 | 01:00:02:21 | 9.04 | 3.72 |
| 84 | 01:00:03:01 | 11.89 | 4.12 |
| 89 | 01:00:03:06 | 12.04 | 3.98 |
| 94 | 01:00:03:11 | 9.18 | 4.23 |
| 99 | 01:00:03:16 | 11.19 | 4.23 |
| 104 | 01:00:03:21 | 12.22 | 5.00 |
| 108 | 01:00:04:00 | 9.58 | 3.87 |

Fireworks scheduled (s from start of working range): 0.46, 0.86, 1.61, 2.74, 5.08, 5.75, 6.65
