# PR-gate real-format fixtures (#1230)

Tiny committed samples in real LAS / DAT / SEGY layouts so the
`test-realdata-smoke` merge-gate job exercises GeoVizEngine.prepare /
SeismicLoader without the large vendor `data/` tree (nightly only).

These are synthetic but format-faithful — not empty stubs. Missing files
must fail the gate (no skip-pass).

| File | Role |
|------|------|
| `A1.Las` | well_log (CWLS 2.0) |
| `ExportWellHead.dat` | well_head (SMI WellHead) |
| `DC.dat` | well_stratification (SMI WellTops) |
| `C3.dat` | horizon (XYZ InlineCrossline) |
| `A1_td.dat` | time_depth (SMI TimeDepth) |
| `tiny.sgy` | seismic (8×8×32 IEEE float32) |
