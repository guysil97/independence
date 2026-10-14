# QC — shot02 (test)

Comp: `test/shot02_comp_rec709_display.mov` · frames 34–108 (TC 01:00:01:01 – 01:00:04:00) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 19.84 · p99.9 5.64 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 19.84 · p99.9 5.42 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.069 % of window lum · max onsets/s 0 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 10-bit hevc: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean -0.09 %, min -2.47 %, max +0.82 %  ·  local change in visible window area (p95 per frame): median 4.1 %, max 17.4 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 34 | 01:00:01:01 | 11.21 | 3.56 |
| 39 | 01:00:01:06 | 9.93 | 3.31 |
| 44 | 01:00:01:11 | 11.13 | 3.50 |
| 49 | 01:00:01:16 | 10.80 | 4.07 |
| 54 | 01:00:01:21 | 8.93 | 3.65 |
| 59 | 01:00:02:01 | 7.68 | 3.32 |
| 64 | 01:00:02:06 | 10.07 | 3.94 |
| 69 | 01:00:02:11 | 12.71 | 4.07 |
| 74 | 01:00:02:16 | 17.06 | 4.04 |
| 79 | 01:00:02:21 | 9.32 | 4.04 |
| 84 | 01:00:03:01 | 9.02 | 3.95 |
| 89 | 01:00:03:06 | 10.71 | 3.95 |
| 94 | 01:00:03:11 | 11.30 | 4.75 |
| 99 | 01:00:03:16 | 10.33 | 4.04 |
| 104 | 01:00:03:21 | 12.22 | 4.84 |
| 108 | 01:00:04:00 | 9.58 | 3.72 |

Fireworks scheduled (s from start of working range): 
