# 06 — IDW / Constrained IDW (§12)

## Plain IDW (engine)
Break-line barriers: node→sample weights zeroed across barrier segments;
nodata cells NaN (never zero). Duplicate coordinates are NOT collapsed
(each well votes; documented). Constraint limitations per the matrix (04).

## Constrained IDW (vendored haiyou adapter)
Provenance discipline unchanged (ATTRIBUTION.md byte-parity + host fixes).
V6 changes:
- `FactorGridResult.from_constrained_idw_dict` preserves the adapter's
  surface-shaping facts: `search_radius`, `decluster_radius`,
  `barrier_buffer_mode`, `duplicate_wells_dropped`, `r_squared_method`,
  `anchored_fidelity(_n_skipped)` (was discarded — audit P1-10).
- Known host-side shaping constants (documented, now visible on results):
  search radius = 1.05× bbox diagonal; decluster radius = 0.15× search;
  direction anisotropy ratio floor 16 / default 18; grid resolution clamp
  20–200; degree-CRS barrier buffer ≈300 m. They remain engine tuning
  (not user parameters) but no longer vanish from provenance.

## Evaluated
`recommend_interpolation_methods` (07) scores it by the same spatial-K-fold
contract as every other method.
