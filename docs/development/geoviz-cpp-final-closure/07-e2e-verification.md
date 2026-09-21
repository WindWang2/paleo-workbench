# 07 — E2E verification

The seven representative scenarios are exercised by product-path test
suites plus a live GUI smoke; each row names where the flow runs against
REAL data (not mocks).

| E2E | Flow | Evidence |
| --- | --- | --- |
| E2E-1 Well | LAS → native parse → viewer → interaction → export | self-check `well_log_dock` (real `tests/fixtures/realdata/A1.Las` through WLE into the dock); viz_a gates (load job → DTO → WellLogHostWidget); export paths in viz-a suites |
| E2E-2 Cross-well | wells → correlation → DTW → picks → save → reopen | `viz_b` suites + VIZ-B sidecar persistence (`cross_well_workspace.json` flush/restore in MainWindow openProject/closeEvent, regression-covered) |
| E2E-3 Well tie | sonic+density → synthetic → auto tie → TD → report | `viz_b.well_tie.oracle` (real-well pipeline, frozen tolerances) + report export |
| E2E-4 Seismic | SEG-Y → inspect → tiled volume → slice → VD/wiggle → attribute → horizon pick → save/reopen | self-check `seismic_chain` (import→rms→publish→view) + `viz_d.widget` picks save/reopen + view-state JSON + slice npy/csv/png + 11-kernel dialog |
| E2E-5 Geo3D | volume → wells → horizons/faults → clip → select → measure → state restore | geo3d 27 suites (clip/measure/views/QC) + **workspace sidecar restore** (this branch) |
| E2E-6 Joint | seismic+wells+TD → joint scene → fences (incl. **manual well-click**) → slices → project switch → restore | `viz_c.joint3d_closure` (real fixtures; project-identity scoping; teardown safety) + `viz_c.joint_analysis` real-.dat stratal + `geo3d_workspace.json`/`joint_analysis.json`/host-QSettings restore across switch |
| E2E-7 Preview | catalog asset → preview registry → presenter → viz | closure-preview pa_flow (143 checks) + data-page adoption suites |

## Live GUI smoke (this branch, final HEAD)

* Real X display (`:0`, xcb): `pwb-platform` interactive launch — process
  stayed alive ≥10 s across repeated runs, window screenshot captured
  (root capture ~195 KB), **error log empty**, exit only via SIGTERM.
  MainWindow + all docks (well log with viewer stack, cross-well, seismic
  slice, Geo3D + joint host, layer tree, three-stage bar) construct in the
  `ui_shell` self-check path.
* Offscreen: `--self-check` **14/14** (well_log_dock live with the WLE
  stack), `--capabilities` 20 hard + well_log_viewer optional + kernel
  rows all `linked runtime-ok`, python-runtime verified.
* GL: the offscreen GL-less paths degrade honestly (geo3d widget suites);
  the on-xcb run exercised the real GL viewport without errors. A
  pixel-level GL comparison remains not-performed (as on main; recorded in
  `11-known-limitations.md`).
