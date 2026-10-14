# Checkpoint 3 — 3-second test renders (Rec.709 proxies)

| | test frames (working range) | TC | crowd seed | firework |
|---|---|---|---|---|
| shot01 | 0–74 | 01:00:23:04 – 01:00:26:03 | 5844 | at 1.6 s (a 3-burst sequence) |
| shot02 | 34–108 | 01:00:01:01 – 01:00:04:00 | 5749 | at 2.6 s (2 bursts) |

Outputs in `test/`: `<shot>_comp_rec709_display.mov` (ProRes 4444, 1920×800 active
area, start TC preserved), `<shot>_preview_709.mp4` (before | after, letterbox
restored), `<shot>_elements_only.mp4` (difference ×4 on black; brightening in its
own colour, darkening in violet), `<shot>_config_used.json`. Reports:
`qc/<shot>_report_test.md`. Stills: `work/<shot>/checkpoint3/`.

## QC (both shots)
| check | shot01 | shot02 |
|---|---|---|
| actor integrity pre-encode (output == source in eroded matte) | PASS, 0 | PASS, 0 |
| actor post-encode, 10-bit CV max / p99.9 | 11.8 / 4.2 | 19.4 / 5.4 |
| …same encode of the untouched source (codec floor) | 12.2 / 4.2 | 19.8 / 5.5 |
| containment (diff outside windows) | PASS, 0 | PASS, 0 |
| flash rule | PASS (2 onsets/s max) | PASS (1 onset/s max) |
| new clipping | PASS, 0 px | PASS, 0 px |

## Magnitudes (scene-linear, visible window area)
* Passers / props: local change (p95 per frame) shot01 2–18 %, shot02 2–5 % (its
  passers in this window are mostly at blinds_B's right edge or beyond frame).
* Fireworks: +15–35 % peak through the transmission map, 0.25–0.8 s decay.
* Door bokeh (shot01): 40–60 px vertical ovals, peak well below the ceiling bokeh.

## Main knobs (config/<shot>.json → elements)
* `light_field.k_gain` (0.22) — overall street-light strength; `cap` (0.28) peak.
* `light_field.occl_max` (0.35) — darkening by close passers.
* `door_bokeh.peak_lin` (0.05) / `max_peak_lin` (0.15) — bokeh brightness.
* `fireworks.at_s`, `peak`, `decay_s`, `multi_burst_prob`.
* `faces.radius_px` / `intensity_level` — calmer area around faces.
* `seed` — a different crowd; `crowd.*` — density, distances, props mix.


## Round 2 — "bolder, a big street parade, specifically Yom Ha'atzmaut evening"
Scenario `independence_day_parade` (config `scenario`, `crowd`, `elements.*`):
* Dense parade flow: groups every 0.6–2.5 s, mostly one direction, 0.3–5 m from the glass
  (14–40 people in front of the windows at any moment).
* Props biased to flag blue (#0038B8) and white: LEDs, light-up Stars of David, flashing
  horn headbands, LED glasses, inflatable hammers, glow sticks, phone torches.
* Pole flags waved above the heads: fluttering shadows in the upper blinds (0.6–1.4 Hz).
* Snow-spray foam puffs catching the street light.
* A parade float per test: cycling blue/white wash, three sweeping moving-head beams
  crossing the storefront, LED bokeh in the door glass.
* The street behind the door glass is lit; the crowd passes as soft silhouettes.
* Municipal fireworks show (white/gold/blue), never two broad flashes < 0.4 s apart.
* Light from emitters is now ADDED through the gaps (scaled to the local backlight) so
  blue/white actually reads; bodies/flags still block the existing light.
* Halo fix: full protection only in the actor core; the effect fades across the soft
  edge with the background share of each pixel.

| | window mean change | local p95 change | QC |
|---|---|---|---|
| shot01 | +21 … +56 % | ~+250 % (door glass was near-black) | all PASS |
| shot02 | +9 … +40 % | +36 … +58 % | all PASS |
