# 09 — Fusion V2 / QC (§16–17)

## Fusion honesty (P1-11 fixes)
- evidence grids with DIFFERENT declared CRSs are REFUSED (was: same-shape
  different-CRS grids fused silently);
- `unit_warnings` in fusion QC: percent-declared grid with 0..1
  normalization bounds; values-vs-declared-unit mismatches (per §14);
- `register_output` persists the CONFIDENCE grid as a best-effort sibling
  catalog version (`confidence_version_id` in QC) and records the
  leave-one-factor-out sensitivity report in provenance (was dead code);
- interpretation preserved: weighted-evidence + rule-based remain the
  fusion families (no black-box default — per program rules).

## Publish gate (§17)
`publish_map_product` fails closed on: superseded · stale fingerprint ·
active QC report with error status · undeclared map CRS (when a
composition exists). Warns (recorded on the report; `accept_warnings=False`
hard-refuses): undeclared factor units · ignored constraint diagnostics ·
missing uncertainty surfaces. Artifacts are versioned, never deleted
(unchanged V5 discipline).

Verified by tests/test_factor_fusion_v6_honesty.py (7) + map product suites.

## QC model (§18)
Typed severity + locatable refs flow through the EXISTING persistence
(project.quality_reports upserted by map id + catalog qc DataRun/OUTPUT
version); V6 checks surface as task quality metrics, constraint
diagnostics, polygon/area QC and gate reports — no second audit database
was created.
