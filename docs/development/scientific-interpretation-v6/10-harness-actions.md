# 10 — Harness Scientific Actions (§19)

`harness/actions/scientific.py` — 5 new typed actions over EXISTING
services (no new agent layer, no new authority):

| action | risk | service wrapped | honest failure |
|---|---|---|---|
| well.describe_units | READ | well_science.depth_unit_of | unknown unit = null + declared=false (never meters) |
| seismic.describe_calibration | READ | hub calibrations | no_calibration entries; velocity never guessed |
| factor.evaluate_methods | COMPUTE | §13 recommendation report | `unavailable` below honest-CV thresholds; capability warnings authoritative |
| map.describe_product | READ | describe_map_product | missing refs → null + reason |
| map.publish | WRITE | §17 gate | refusals carry the reason; warnings recorded |

Registry now exposes 56 actions. Remaining gaps from the §19 list
(well.validate/process_curve/resample/list_tops, seismic.validate_geometry,
factor.prepare_samples/interpolate/compute_uncertainty/compare/fuse) are
documented as known limitations (13) — the wrapped services exist; the
action surface is deliberately incremental (only actions whose honesty
contract could be fully specified shipped this round).
