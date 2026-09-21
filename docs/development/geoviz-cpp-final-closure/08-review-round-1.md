# 08 — Review round 1 (five independent reviewers)

Reviewers: A migration completeness · B architecture/memory/concurrency ·
C scientific parity · D+E product wiring/UX · F build/platform. All
verdicts against `03e7dacf`.

## Findings → dispositions (fixed in 38b690e0 unless noted)

| ID | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| B-P0-1 / D-P1 | **P0** | joint-analysis job callbacks ran GUI work on the WORKER thread (unlocked SceneObjectManager writes, QLabel::setText, worker-thread QDialog) — violated the frozen viz_b job_bridge contract | FIXED: on_finished queued-hop pattern; any_cast results; QPointer guards |
| B-P0-2 | **P0** | raw Page*/host*/manager* in job closures → UAF windows after teardown | FIXED by the same hop (released-guard drops queued deliveries) + QPointer |
| B-P0-3 | **P0** | SceneObjectManager data race (unordered_map rehash vs GUI reads) | FIXED (writes now GUI-thread) |
| C-P0-1 | **P0** | header-only/wrong `.dat` selection → `parse_horizon_text` std::invalid_argument on the GUI thread → std::terminate | FIXED: parsing moved into the worker (grids_fn); exceptions become job error strings |
| A-P1-1 / C-P1-1 | **P1** | stratal real-path overlays built in world-XY/TWT-ms vs the viewport's preview-index render space (only the demo path was tested) | FIXED: verts = (i, x, s); real-.dat E2E test added (round 2) |
| B-P1-1 | P1 | no stale-delivery guard across project switch | FIXED: directory identity + (round 2) registration identity |
| B-P1-2 | P1 | grids parsing blocked the GUI thread | FIXED (same grids_fn move) |
| F-P1 / D-P2 | P1/P2 | PWB_WITH_JOINT_ANALYSIS gate mismatch → reduced-config link failure | FIXED: root-emitted define, all call sites gated |
| A-P2-1 / B-P2-2 | P2 | sidecar writes non-atomic | FIXED: QSaveFile (+ round-2: commit failures surfaced) |
| A-P2-2 | P2 | sweetness/relative_impedance wrongly refused on 2D sections ("needs 3-D") | FIXED: added to is_section_kernel; refusal text corrected; round-2 added the depth-domain gate for sweetness |
| F-P2 | P2 | `Pwb::Geomodel` probe alias never existed | FIXED: `Pwb::GeoModel` (+ round-2: row title/detail updated) |
| B-P2-1 | P2 | geo3d unreadable sidecar leaked previous project | FIXED: reset; round-2 extended the same isolation to the corrupt branch |
| D-P2 | P2 | joint-host state not flushed on close (click-added fences lost) | FIXED: save_state() in both flush paths |
| C-P2-2 | P2 | migration docs stale vs HEAD | FIXED: regenerated at final HEAD |
| A-P1-2 | P1 | stratal surfaces render untextured (no amplitude extraction through the seam) | ACCEPTED as documented limitation #4 (kernel exists; volume-input seam is the follow-up) |
| A-P2-3 | P2 | arbitrary-line / 2D fence profile / professional graticule export = Python-only product capabilities | ACCEPTED as limitations #1–#3 (explicit unfinished migration, not hidden) |
| D/E/B P3s | P3 | dead code (`geo3d` dep, `interp:` trim, tie_freq), export suffix edges, owners_ growth, panel positive-feedback | fixed where touched this branch (dead surfaces removed); pre-existing P3 patterns recorded |

## Reviewer-confirmed clean areas

well_clicked semantics (byte-level Python parity incl. refusal text),
stratal grid semantics vs `build_stratal_grids` (stride-lattice exactness,
fill_nearest parity, soft-fail texts), RGB fusion port (line-audit),
振幅 leaf + wiggle escape (with regressions), matrix tool methodology,
C3 registration (no id collision; coexistence contract intact),
openProject/closeEvent flush ordering, geo3d/joint/QSettings state
orthogonality.
