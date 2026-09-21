# 10 — Bugs fixed (this branch)

1. **Worker-thread GUI work** in all three joint-analysis job hooks
   ( SceneObjectManager races / worker QDialog ) — rebuilt on the queued
   on_finished hop. [r1 P0]
2. **GUI-thread crash on non-numeric `.dat`** (std::terminate via
   parse_horizon_text) — parsing moved into the job worker; errors become
   status strings. [r1 P0]
3. **Stratal real-path overlays in the wrong coordinate system** — now
   preview-index render space; E2E'd against a real volume. [r1 P1]
4. **Demo flag never propagated** to StratalInput (演示地层切片 button
   would have soft-failed in the product) — caught by the new test suite
   before release. [in-session]
5. **Reduced-config link failure** (PWB_WITH_JOINT_ANALYSIS gate mismatch)
   — root-emitted define + gated call sites. [r1 P1]
6. **NATIVE_PRODUCT + WLE viewer stack never configured** (data_suite /
   CONV-09 duplicate add collisions) — TARGET guards. [in-session]
7. **Unreachable clear-attribute action** (export refusal pointed at an
   action no UI exposed) — 振幅 leaf. [in-session]
8. **Invisible-but-active pinned attribute** after switching to wiggle —
   pin abandoned on switch. [in-session]
9. **well_clicked signal with zero consumers** (documented click-to-fence
   flow unreachable) — connected to the 1:1-ported scene API. [in-session]
10. **C3 kernel unreachable from any product path** — registered in the
    product runner (kernel + 7-fixture oracle already existed in
    `libs/algorithms`; a duplicate port written first was caught and
    removed). [in-session]
11. **Sweetness/relative-impedance falsely refused on 2D sections**; then
    sweetness **allowed on depth-domain volumes with bogus units** — both
    gated correctly. [r1 P2 + r2 P1]
12. **Geo3D workspace never persisted**; plus corrupt/unreadable sidecar
    branches leaked the previous project — seven-key sidecar with atomic
    writes and reset-on-any-restore-failure. [r1+r2]
13. **Joint host scene state lost on window close** (fences) — flushed in
    both close paths. [r1 P2]
14. **Sidecar truncation on crash** — QSaveFile atomic commits, failures
    surfaced. [r1/r2 P2]
15. **Stale stratal delivery across project/volume switches** — directory
    + registration identity guards. [r1+r2]
16. **`Pwb::Geomodel` probe typo** (capability row always absent) +
    stale geomodel capability wording — corrected + consumer-aware. [r1/r2]
17. **Migration-matrix methodology defects (#1448 family)** — aliases,
    transitive link closure, TU-consumer evidence; matrix regenerated
    (bidirectional: ~88 fake-NOT_WIRED rows recovered, TU gate prevents
    fake NATIVE_PRODUCT). [in-session]
18. **Dead surfaces** removed (run_modeling hook, `geo3d` dep,
    set_well_tie_result, tie_freq, tool dead code). [r1/r2 P3s]
19. Test-rig destruction-order UAF (JobCenter vs host QObject-child
    owners) — fixed with the HostRig contract, now documented in the rig.
    [r2, caught by the new E2E]
