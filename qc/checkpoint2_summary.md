# Checkpoint 2 — actor mattes (proxies)

SAM 2.1 **base_plus** on CPU (shot02 171 f ≈ 20 min, shot01 125 f ≈ 33 min), then
guided-filter edge refinement, a 12 px soft protection falloff and flow-compensated
temporal stabilisation. Images/videos: `work/<shot>/checkpoint2/`; mattes:
`work/<shot>/mattes/`. Prompts are editable in `config/prompts/<shot>.json`.

| | objects (all protected) | edge chatter, mean dP in edge band (median / p95) |
|---|---|---|
| shot01 | matan, stick (from ~f95, entering motion-blurred from the left edge) | 0.096 / 0.23 |
| shot02 | matan, sara | 0.038 / 0.076 |

## What the matte does
* `actors_alpha` — union soft alpha. Guided filter runs on the SAM mask dilated
  8 px with the plate as guide, so alpha reaches into frizzy hair and falls back
  where the plate looks like background.
* Enclosed gaps in the union up to 6000 px (e.g. between his forearm and her
  shoulder, shot02 f140) are filled: treated as actor — the safe side.
* `protection` — alpha + 12 px smoothstep falloff; effects are multiplied by
  (1 − protection). Temporally averaged ±1 frame along optical flow, only where the
  warp is photometrically consistent, and never smaller than the current alpha.
* `integrity` — alpha > 0.5 eroded 3 px: output pixels there are copied from the
  decoded source.

## Fixes made while checking
* shot02: SAM intermittently included Matan's **reflection in the glass counter**
  (main source of chatter) → exclusion polygon below the counter edge (actors stand
  behind it).
* With real mattes the transmission maps are now a **clean-plate median** (actors
  removed). That revealed in shot01 three more interior ceiling-light bokeh discs
  and the counter objects inside blinds_A → masked / polygon notched.
* shot01 `frosted_panels` added as `diffuse_glass` (own smooth transmission).

## Known limits
* Single flyaway hairs a few px wide may sit just outside alpha; they are inside
  the 12 px protection band in every QC frame checked.
* Pixels that an actor covers in (almost) every frame have transmission 0 — never
  visible, never lit.
