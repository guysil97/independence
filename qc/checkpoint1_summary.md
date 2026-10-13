# Checkpoint 1 — look-dev proxies (Rec.709, display-referred)

Inputs are graded Rec.709 exports with 2.40 letterbox baked in; processing is on the
1920×800 active area, linearised with BT.1886 γ2.4. Images: `work/<shot>/checkpoint1/`.
Raw numbers: `work/<shot>/analysis.json`, `work/<shot>/probe.json`.

## Edit points found inside the delivered files
| file | cuts at plate frame |
|---|---|
| shot01 (`independance_day.mov`, 843 f, TC 01:00:11:00) | 165, 304, 434 |
| shot02 (`independance_day_1.mov`, 172 f, TC 00:59:59:17) | 171 (last frame is the next shot) |

Working ranges (single takes, verified cut-free):
* **shot01: plate frames 304–428 = TC 01:00:23:04 – 01:00:28:03** (125 f, 5.0 s)
* **shot02: plate frames 0–170 = TC 00:59:59:17 – 01:00:06:12** (171 f, 6.84 s)

## Camera motion (not locked off — regions and all elements must be tracked)
| | max drift vs ref | frame-to-frame (median / max) | ECC corr (min / median) |
|---|---|---|---|
| shot01 storefront | 18.8 px | 0.67 / 2.55 px | 0.96 / 0.99 |
| shot02 storefront | 15.0 px | 0.21 / 1.24 px | 0.99 / 1.00 |

shot01: blinds and door are tracked as one storefront plane (affine) using only
the door area the actor never covers; the blinds alone are mostly hidden by his
head and their 15 px slat pitch aliases the tracker. Spot-checked against
template matching: agreement within ~1–4 px. Re-run with real mattes after CP2.

## Blinds
| | slat pitch | angle | slat/gap lum (linear) | note |
|---|---|---|---|---|
| shot01 blinds_A | 15.5 px | −0.0° | 0.83 | heavily defocused, low slat contrast |
| shot02 blinds_A | 8.9 px | +1.2° | 0.49 | |
| shot02 blinds_B | 13.2 px | −2.0° | 0.22 | **gaps already clip at code 1.0** |

## Bokeh (shot01)
Reference for door-plane bokeh = defocused glint on the door handle:
**31 × 44 px, vertical oval (aspect 1.43 ≈ 1.5× anamorphic), 10–90 % edge ≈ 15 px,
centre-weighted (rim/core 0.79), smooth interior (no onion rings)**.
Interior ceiling discs over the blinds are ~46 × 30 px with a flat top
(vignetted) — masked as foreground, never relit.

## Noise (temporal, stabilised neighbours, 10-bit CV)
shot01 blinds 1.1–2.8, door 0.1–1.7; shot02 blinds 0.7–3.2. Grain is soft
(lag-1 correlation 0.6–0.7) — compression has smoothed it; brighter areas are
cleaner (codec flattening).

## Levels in regions (code values, 0–1)
| | black p0.1 | highlight p99.99 | max |
|---|---|---|---|
| shot01 blinds_A | 0.027 | 0.78 | 0.79 |
| shot01 door_glass | 0.027 | 0.93 | 0.95 |
| shot02 blinds_A | 0.021 | 0.95 | 1.00 |
| shot02 blinds_B | 0.036 | 1.00 | 1.00 |

## Proxy limitations (flagged, not fought)
* shot01 is 8-bit H.264: 168 distinct green codes in blinds_A, visible macroblocks.
  Transmission map smoothed 2 px for this reason (config).
* shot02 blinds already clip → upward lifts there must be soft-limited.
