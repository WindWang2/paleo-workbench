# 08 — Single-Factor Map Scientific Contract (§14–15)

## Every factor result carries
factor identity/type, input versions (source_refs), well sample identities
(sample_points carry well_id), declared unit, CRS (None = undeclared, never
guessed), algorithm id + parameters (incl. constraint_diagnostics from §10
and distance-policy annotation from D5), grid + nodata (NaN), uncertainty
(variance grid for kriging; anchored fidelity for constrained IDW),
QC/quality metrics, run/provenance, freshness fingerprint.

## Unit authority (§14)
`workflow/factor_units.py` remains the single name-alias authority
(unknown → None). NEW: `validate_factor_unit_against_values` cross-checks
the declared unit against value magnitudes (a "%" unit on 0..1 fractions —
and the inverse — is a diagnostic, never silently misclassification);
wired into fusion evidence checks.

## Geometry QA (§15, P0-10)
`mapping/geological_pipeline/geometry_units.py`: CRS classification +
unit-labelled measures. Under a geographic CRS per-feature areas carry
`area_unit: "deg²"` + an explicitly-labelled local-scale
`area_approx_m2`; undeclared CRS labels `unknown-unit²` — square degrees
can no longer masquerade as m². `polygon_qc` now records the
classification thresholds + source (explicit vs data-derived ⅓/⅔ default),
nodata/total cell counts, and area warnings.

Verified by tests/test_geometry_units_qa.py (12); adversarial conservation
suites stay green (raw-area semantics preserved, now labelled).
