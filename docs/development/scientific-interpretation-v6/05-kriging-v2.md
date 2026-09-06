# 05 — Kriging V2 (§11)

## What changed (geoviz_plots/factor/kriging.py)
- **Geometric anisotropy**: `apply_anisotropy_transform(azimuth_deg,
  ratio)` maps samples AND targets into the isotropic frame (geological
  azimuth convention — clockwise from north, matching the directional
  backend; ratio = major/minor ≥ 1 EXPANDS the minor axis). The isotropic
  solve in that frame is exactly the anisotropic model with range =
  major-axis range. `ordinary_kriging(..., azimuth_deg=, anisotropy_ratio=)`.
- **Explicit variogram controls**: `variogram_model/range_/nugget` honored
  verbatim; routed from task parameters (`variogram_model`,
  `variogram_range`/`range_m`, `variogram_nugget`/`nugget`) through
  `interpolate_factor_grid`.
- **Fit honesty**: a `diagnostics` dict reports the variogram that produced
  the surface and HOW its parameters were chosen
  (`fitted`/`defaulted`/`explicit`) + anisotropy — silent auto-fit is over.
- **Fit quality**: default lag extent = half the SMALLER axis extent
  (full-diagonal bins mixed correlated and uncorrelated pairs into the
  first bin and collapsed the fit to a nugget).
- Existing strengths kept: exact LOO, kriging variance, duplicate
  mean-collapse, ridge/lstsq singular fallback, fail-closed non-finite.

## Numerical evidence
Stationary anisotropic GRF (Gaussian covariance, 200 m / 40 m ranges, ratio
5, n=2500, 300 holdouts): anisotropic kriging RMSE **0.037** vs isotropic
**0.202** (spherical), **0.046** vs **0.104** (exponential). Verified in
tests/test_kriging_v2.py.

## Barriers
Explicitly UNSUPPORTED for kriging (capability matrix); no fake penalty
kriging was implemented. A scientifically defensible barrier covariance
method remains future work (see 13).
