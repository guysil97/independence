# QC — shot02 (test)

Comp: `test/shot02_comp_rec709_display.mov` · frames 34–37 (TC 01:00:01:01 – 01:00:01:04) · 4 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 13.41 · p99.9 3.92 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 12.04 · p99.9 3.81 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.087 % of window lum · max onsets/s 0 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 10-bit hevc: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +0.67 %, min +0.60 %, max +0.80 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 34 | 01:00:01:01 | 11.21 | 3.59 |
| 37 | 01:00:01:04 | 6.62 | 3.28 |

Fireworks scheduled (s from start of working range): 2.60, 3.26
