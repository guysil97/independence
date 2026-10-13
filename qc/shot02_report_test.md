# QC — shot02 (test)

Comp: `test/shot02_comp_rec709_display.mov` · frames 34–108 (TC 01:00:01:01 – 01:00:04:00) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 19.37 · p99.9 5.35 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 19.84 · p99.9 5.46 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.044 % of window lum · max onsets/s 1 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 10-bit hevc: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +8.14 %, min +0.31 %, max +25.92 %  ·  local change in visible window area (p95 per frame): median 9.0 %, max 34.2 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 34 | 01:00:01:01 | 11.21 | 3.59 |
| 39 | 01:00:01:06 | 9.93 | 3.26 |
| 44 | 01:00:01:11 | 11.30 | 3.37 |
| 49 | 01:00:01:16 | 9.32 | 3.67 |
| 54 | 01:00:01:21 | 8.93 | 3.53 |
| 59 | 01:00:02:01 | 8.09 | 3.04 |
| 64 | 01:00:02:06 | 15.52 | 4.12 |
| 69 | 01:00:02:11 | 11.02 | 4.21 |
| 74 | 01:00:02:16 | 17.25 | 4.39 |
| 79 | 01:00:02:21 | 9.32 | 3.87 |
| 84 | 01:00:03:01 | 12.04 | 4.14 |
| 89 | 01:00:03:06 | 12.04 | 3.98 |
| 94 | 01:00:03:11 | 11.10 | 4.60 |
| 99 | 01:00:03:16 | 11.19 | 4.37 |
| 104 | 01:00:03:21 | 12.22 | 4.92 |
| 108 | 01:00:04:00 | 9.58 | 3.82 |

Fireworks scheduled (s from start of working range): 2.60, 3.26
