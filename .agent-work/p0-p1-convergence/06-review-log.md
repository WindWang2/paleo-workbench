# 06 — Review Log

## Round 1 (two-axis, fixed point = origin/main merge-base)

Standards + Spec axes run as parallel sub-agents (Matt /code-review
methodology). Full findings with dispositions:

### BLOCKER

1. **Paged mode died on the second refresh** (Spec). `update_paged` read a
   nonexistent `provider` attribute on the model → AttributeError → silent
   fallback to full materialization from refresh #2 — the exact 100k gap
   the slice closes. **FIXED**: provider property + regression test
   (second `update_paged` stays in paged mode).

### HIGH

2. **CompositionPanel bypassed the edit session** (Standards: component
   contract "undoable through ONE session"). Geometry/title/visibility
   wrote fields directly → non-undoable, revision stale. **FIXED**:
   move/scale/configure/set_element_visible commands + session routing.
3. **Derived LAS staged inside the RAW store, never cleaned** (Standards:
   managed storage / RAW immutability). **FIXED**: tempfile staging,
   unlink on every path, run_id from the version's own field.
4. **Well display name used as depth_cursor identity** (Standards:
   JointWellId). **RESOLVED-BY-DOCUMENTATION**: the cross-view well key is
   the registered hub key (name) by the established #1029 contract every
   view publishes; SelectionState docstring now states this explicitly.
   Switching keys project-wide would touch every view for no behavioral
   gain — recorded as deliberate, not silent.
5. **MAIN_MAP never received map data from the UI** (Spec: factor→layer→
   template→export). **FIXED**: `CompositionPanel.set_main_map` bound from
   the mapping page's active-document changes.
6. **Serialization dropped data bindings with no re-bind path** (Spec).
   **FIXED**: `bind_map_documents(comp_doc, {id: MapDocument})` re-binds
   MAIN_MAP/INSET_MAP from serialized reference stubs after from_dict;
   unresolvable stubs honestly render the unbound placeholder.
7. **Scenario B "→3D" not closed** (Spec). **FIXED**: 3D page
   `focus_seismic_position` (IL/XL slices; sample only when TWT maps onto
   the loaded volume's sampling); app_shell fans the cursor to BOTH the
   seismic panel and the joint scene.
8. **Scenario C had no production calibration author** (Spec). **FIXED**:
   `bind_project` parses time_depth assets (EntityAssetLink role first,
   legacy typed resources second) into TimeDepthCalibration registrations
   in the hub; non-monotonic tables refused.
9. **Scenario D published but consumed by no view** (Spec). **FIXED**:
   app_shell registers the 3D page's `highlight_interpretation` as the
   horizon sink (stratal combo preselection by interpretation id).

### MEDIUM

10. Constant-velocity MD presented without qualification →
    `seismic_well_md_is_approximate: True` flag + docstring (the value
    itself stays: pinned contract, readout-only consumer).
11. Duplicate `_refresh` in data_page (diff artifact) → dead copy deleted.
12. `set_picks` reached into mesh undo-stack privates → public
    `SculptableHorizonMesh.set_heights` (single sanctioned mutation path).
13. run_id recovered by scanning document.runs → read from the version's
    own `run_id` field (scan kept as fallback only).
14. MapProduct staging temp never unlinked → `finally` cleanup (catalog
    copies the payload into the managed OUTPUT store).
15. Scenario C refusal surfaces only at debug level — accepted for now
    (the refusal is behavioral: no seismic navigation happens), noted as
    follow-up to surface in the seismic panel status line.

### LOW (recorded, not fixed — judgement calls with rationale)

- Data clump: the 7-field filter tuple across paged-query signatures —
  a named dataclass would churn db.py's established style for no behavior
  change.
- Renderer type-cascade (elif per ElementType) — mirrors the file's
  existing structure; dict dispatch would be a stylistic rewrite.
- Message chains at the engine boundary (`view._profile_il._vd...`) —
  all guarded getattr seams over engine internals by design (the panel
  degrades when internals evolve).
- Attribute label → engine combo routing is best-effort by text (the
  engine combo has its own vocabulary); pre-existing seam.
- Scope note: `.agent-work/`, `run_env.sh`, CONTEXT.md are process
  artifacts the goal explicitly sanctioned (repo convention keeps them).

### Verified clean (both axes)

No second Catalog/selection-bus/LayerRegistry/scheduler/volume-IO; paged
mode reuses `service.index`; RAW untouched (bytes pinned by test);
fail-closed calibrations; trace-global FFT refusal; anti-laundering;
GUI-thread discipline; budgets tested at 100k.

## Round 2

Verification pass over every Round-1 fix (diff re-read + targeted tests):
all fixes hold, no new findings at BLOCKER/HIGH. Regression state after
fixes: targeted modules green; full-suite re-run recorded in 07.

**Final counts: BLOCKER 0, HIGH 0** (HIGH #4 resolved by documented
deliberate contract), MEDIUM fixed except #15 (recorded follow-up), LOW
recorded with rationale.
