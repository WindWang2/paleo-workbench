# 09 — Review round 2 (adversarial)

Two adversarial reviewers against `38b690e0` + the merged tree, targeting
confirmation bias, stale tests, dead gates, and fix-regressions.

## Findings → dispositions

| ID | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| 2a-P0-1/2 | **P0 (attribution corrected)** | closure_seismic / viz_b-LAS product gates sat forever-false in `apps/` | NOT introduced by this branch (fork-point state; the round-1 TU audit had missed the apps-side dead gates). **Fixed by merging origin/main #1453**, whose post-hoc root wiring restored both (verified: root `CLOSURE-SEISMIC` block + `VIZ_B_LAS` block now compiled). Added to this ledger so the attribution is on record |
| 2a-P0-3 / 2b-P1-3 | **P0/P1** | geo3d corrupt (readable-but-bad-JSON) sidecar branch did NOT reset — the round-1 "isolation" claim was half-true | FIXED: catch branch resets + refreshes + honest status |
| 2b-P1-1 | **P1** | stratal real-path test was vacuous (predicate true before the call); `stratal_status_text()` verifier surface had zero callers | FIXED: refusal texts asserted; **real-volume .dat E2E added** (open frozen survey → write horizons on its actual axes → hook → render-space overlay with z within sample bounds); the E2E itself then caught a destruction-order UAF in the test rig (fixed with the joint3d HostRig pattern) |
| 2b-P1-2 | P1 | `Pwb::VisualizationWellTie` gate/link survived the auto-tie rewrite that removed its last use — VIZ_B=OFF silently dropped the whole joint-analysis install | FIXED: dropped from both gates; comment keeps the history |
| 2a-P1-1 | P1 | sweetness ran on depth-domain volumes with a bogus default dt (same time-axis dependency as instantaneous frequency) | FIXED: depth-domain refusal for sweetness + freq |
| 2a-P1-2 | P1 | `PWB_BUILD_CATALOG_CLOSURE` option gate forever-false | Inherited fork-point state; main #1453 owns the catalog-closure wiring — verified present after merge |
| 2b-P1-4 | P1 | geomodel capability row self-contradictory ("仅内核未接线" while joint-analysis consumes it) | FIXED: title + runtime detail reflect the consumer |
| 2a-P2-1 | P2 | "known gaps recorded in the ledger" existed only in a commit message | FIXED by this document set (limitations written into `11-known-limitations.md` — the reviewer was right) |
| 2a-P2-2 | P2 | stale guard keyed only on directory (volume switch within a project passed) | FIXED: + registration-pointer identity |
| 2a-P2-3 | P2 | QSaveFile::commit() ignored | FIXED: surfaced |
| 2b-P2-1 | P2 | binding-layer coverage gap for the new inline kernels (sweetness/relImp/振幅) | Partially closed (kernel-layer oracles pre-exist; real-.dat E2E covers the new plumbing); binding-level per-kernel cases noted as follow-up in `11-#7` |
| 2b-P2-2 | P2 | committed matrix evidence drifted (line numbers, missing new TU as consumer) | FIXED: matrix regenerated at final HEAD |
| 2b-P2-3 / 2a-P3 | P3 | dead surfaces (`set_well_tie_result`, `geo3d` field), demo/real z-sign divergence documented, export/advisor silent no-op on null jobs | FIXED (dead surfaces removed); z-sign noted in-code; null-jobs silent return aligned with other hooks' fail() text where reachable |

## Verified-clean (round 2, explicitly)

on_finished delivery contract (all JobState branches incl. degraded),
VolumeRegistration copyability, exception→error-string chain for
grids_fn, QPointer/TOCTOU safety, PWB_WITH_JOINT_ANALYSIS reduced-config
re-derivation (SEISMIC_VIEWER=OFF / VIZ_B=OFF / CONV_22-missing paths),
sweetness parameter validation, render-space fix correctness vs
`world_to_render_xyz`, RGB/demos against `demo.py`, C3 include guards,
matrix tool reproducibility (inventory reruns byte-identical).
