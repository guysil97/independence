# QC — shot01 (test)

Comp: `test/shot01_comp_rec709_display.mov` · frames 0–0 (TC 01:00:23:04 – 01:00:23:04) · 1 frames

| check | result | value |
|---|---|---|
| actor integrity, pre-encode (eroded matte, output == decoded source) | PASS | max diff 0.00e+00 |
| actor fully-protected zone untouched (protection = 1) | PASS | max diff 0.00e+00 |
| actor integrity, post-encode (ProRes 4444 round trip, 10-bit CV) | info | max 10.26 · p99.9 3.52 (worst frame) |
| codec baseline: untouched source through the same encode (10-bit CV) | info | max 7.76 · p99.9 3.43 |
| region containment (diff outside windows) | PASS | max 0.00e+00 |
| flash rule (>3 Hz oscillation excl. fireworks; broad flash onsets per second) | PASS | >3 Hz rms 0.000 % of window lum · max onsets/s 0 |
| new clipping in windows | PASS | 0 px total |
| banding | flag | source is 8-bit h264: banding/blocking in the plate itself is not fought (proxy) |

Window luminance change introduced (relative): mean +26.33 %, min +26.33 %, max +26.33 %  ·  local change in visible window area (p95 per frame): median 178.7 %, max 178.7 %

Per-frame post-encode integrity (10-bit CV, max / p99.9):

| frame | TC | max | p99.9 |
|---|---|---|---|
| 0 | 01:00:23:04 | 10.26 | 3.52 |

Fireworks scheduled (s from start of working range): 2.42, 2.86, 3.92, 4.44
