# 03 — Coordinate / Calibration Chain (§8–9)

## Hub grid honesty (P1-6)
`CoordinateTransformHub` carries `_grid_configured`; until a survey is
bound, `map_to_seismic_xy`/`seismic_to_map_xy` raise
`no seismic grid configured` (typed `NO_GRID` failure in domain_coords).
`well_md_to_seismic_cursor` degrades to None instead of fabricating
(IL,XL). The no-argument `configure_seismic_grid()` reset restores UNKNOWN
(cross-project residue guard). All existing callers already degrade on
ValueError (verified by updated view-coordination tests).

## SEG-Y scalar unification (P0-4)
`geoviz_seismic.loader.apply_source_group_scalar` is THE canonical helper
(>0 multiply, <0 divide, 0 = documented metres convention). The
`segy_survey` trace-scan corners and inline-spacing measurement now apply
the per-trace scalar; inconsistent scalars across corner traces set
`scalar_inconsistent` in the survey meta + warning.

## Degenerate geometry refusal (P0-5)
`survey_from_corners` refuses zero-extent edges — all-zero SourceX/Y can no
longer fabricate a valid-looking 1 m-bin survey at the origin.

## TD range honesty (P1-4)
`TimeDepthTable` conversions are NaN outside the calibrated range (was
edge-value clamp); trajectory builders truncate to the calibrated range
with an explicit warning; scene curve/track consumers drop uncalibrated
samples. This matches the hub's fail-closed TimeDepthCalibration policy.

## Verified by
engine tests: test_segy_scalar_geometry.py (9), test_time_depth_range_honesty.py (6);
superproject: test_coordinate_hub_honesty.py (6) + view-coordination suites.
