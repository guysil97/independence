# QC — shot01 (test)

Comp: `test/shot01_comp_rec709_display.mov` · frames 0–74 (TC 01:00:23:04 – 01:00:26:03) · 75 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 11.79 · p99.9 4.23 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 12.24 · p99.9 4.23 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.091 % of window lum · max onsets/s 1 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 8-bit h264: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +30.16 %, min +21.72 %, max +55.88 %  ·  local change in visible window area (p95 per frame): median 257.1 %, max 296.2 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 0 | 01:00:23:04 | 9.68 | 3.59 |
| 5 | 01:00:23:09 | 9.76 | 3.48 |
| 10 | 01:00:23:14 | 7.48 | 3.73 |
| 15 | 01:00:23:19 | 10.26 | 3.76 |
| 20 | 01:00:23:24 | 7.73 | 3.93 |
| 25 | 01:00:24:04 | 9.43 | 4.09 |
| 30 | 01:00:24:09 | 11.49 | 4.23 |
| 35 | 01:00:24:14 | 10.35 | 3.75 |
| 40 | 01:00:24:19 | 8.76 | 3.98 |
| 45 | 01:00:24:24 | 7.41 | 3.62 |
| 50 | 01:00:25:04 | 6.20 | 2.79 |
| 55 | 01:00:25:09 | 5.00 | 2.92 |
| 60 | 01:00:25:14 | 5.76 | 2.89 |
| 65 | 01:00:25:19 | 5.40 | 2.89 |
| 70 | 01:00:25:24 | 5.48 | 2.90 |
| 74 | 01:00:26:03 | 4.89 | 2.87 |

Fireworks scheduled (s from start of working range): 2.42, 2.86, 3.92, 4.44
