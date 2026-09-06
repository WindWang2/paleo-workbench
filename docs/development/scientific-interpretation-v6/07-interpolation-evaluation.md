# 07 — Interpolation Evaluation Workbench (§13)

`paleo_workbench/workflow/interpolation_evaluation.py`:

- **Spatial K-fold surface CV** (pre-existing #921 discipline): sectors as
  folds, bilinear scoring, nodata-touching holdouts SKIPPED not faked,
  duplicate-coordinate collapse, honest None below thresholds.
- **Leave-one-well-out** (new): `leave_one_well_out_folds` groups samples
  by `well_id` (name fallback; anonymous = singleton) — the honest scheme
  when well-level bias is the question.
- **Metrics**: RMSE / MAE / bias / signed R² (`signed_r_squared` — worse
  than mean is negative), n_samples / n_skipped; residuals per point
  (spatial residual layer input).
- **Cross-method recommendation** (new): `recommend_interpolation_methods`
  runs every method through the SAME fold engine and returns per-method
  metrics + capability warnings + recommended/rationale. A method that
  ignores requested constraints is DISQUALIFIED regardless of metrics.
- Exposed to agents as `factor.evaluate_methods` (§19).

Verified by tests/test_evaluation_workbench.py (12).
