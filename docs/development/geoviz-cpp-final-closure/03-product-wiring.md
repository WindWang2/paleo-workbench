# 03 — Product wiring closed by this branch

All items below were "seam exists, no product entry" or "kernel exists,
no product path" states at the fork point. Each row names the composition
root that now reaches it (target → CMake feature → AppContext/service →
MainWindow/AppShell → user action).

| Wiring | Chain | Commit |
| --- | --- | --- |
| 振幅 leaf = clear-attribute entry | panel vocabulary `amplitude` pseudo-kernel → `closure_seismic::on_attribute` → `SeismicSliceWidget::clear_attribute_view` | d283c715 |
| Wiggle switch abandons pinned attribute | `SeismicSliceWidget::set_display_mode` → `clear_attribute_view` (export refusal dead-end removed) | d283c715 |
| Manual fence (click-to-append) | `VizCTimeSliceMap::well_clicked` (was: zero consumers) → `WellSeismicScene::append_fence_well` → well-order fence sync → prep pipeline | d283c715 |
| Joint analysis hooks | root CMake `PWB_WITH_JOINT_ANALYSIS` gate → `joint_analysis_install.cpp` → page `set_analysis_hooks`: stratal (demo + real .dat via `grids_fn` on the job worker), RGB overlay, crossplot (native `analyze_lithology_crossplot` + geomodel litho tables), FLAC3D/Abaqus export, advisor, sidecar persistence | d283c715 + 38b690e0 |
| Geo3D workspace persistence | `Geo3DDock::persist/restore_project_workspace` (seven-key payload → `geo3d_workspace.json`, QSaveFile atomic, corrupt/unreadable → reset) + MainWindow flush/restore on project switch & close | d283c715 + 38b690e0 |
| Joint-analysis state persistence | `joint_analysis.json` sidecar (joint_state codec) + page `set_project` restore path | d283c715 |
| Joint-host scene state on close | `joint_host()->save_state()` added to both flush paths (fences survived only volume-load/switch before) | 38b690e0 |
| C3 coherence in the product runner | `pwb::science::algorithms::make_coherence_c3` registered in `AppContext::registerProductKernels` (kernel existed, was unreachable; **11 kernels** now) | 4b292bca |
| 2D panel inline sweetness/relative-impedance | `is_section_kernel` extended (both are per-trace chains in the Python panel too); structural kernels still honestly refused with a pointer to the volume dialog; sweetness gated to time-axis volumes | d283c715 + post-r2 |
| NATIVE_PRODUCT + WLE viewer stack configure | data_suite/CONV-09 TARGET guards (this combination had never configured on main) | d283c715 |
| closure_seismic / viz_b LAS / catalog-closure product gates | inherited from main #1453 (post-hoc root wiring) via the mid-flight merge | 73628b40 (merge) |

## Wiring gates (verified)

`PWB_WITH_JOINT_ANALYSIS` is emitted from the root VIZ-C-host block only
when **UiWorkers + SeismicViewer + GeoModel + the full AppShell target
set** exist; every `main_window.cpp` call site compiles under that define
(reduced SEISMIC_VIEWER=OFF / VIZ_B=OFF configurations degrade to the
page's honest 未接入 fallbacks instead of link-failing — the round-2
adversarial review pushed this gate through explicit reduced-config
re-derivation).
