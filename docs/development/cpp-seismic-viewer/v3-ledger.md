# CPP-D v3 Ledger — Seismic 2-D Slice Viewer

Branch `codex/cpp-v2-seismic-viewer` (worktree `.worktrees/cpp-v2-seismic-viewer`, created fresh from base `53e22b67`).
Scope: `libs/seismic_viewer/`, `tests/cpp/seismic_viewer/`, `docs/development/cpp-seismic-viewer/` only.
Limit: 15 focused rounds.

Host note: this session runs on the Linux mirror of the repo (prompt paths are
Windows); the worktree/branch/base-SHA identities match the protocol. The
PowerShell gate is unavailable (no pwsh) — its semantics (exclusive
`<git-common-dir>/cpp-migration-heavy.lock` + ≥8 GiB + jobs=2 + build under
`worktree/build` + `ctest --no-tests=error --timeout 180`) are honored via an
equivalent flock wrapper; first cross-line contention already observed and
respected (A-line held the slot, D waited).

| Round | Change | Verification | Result | Next |
|---|---|---|---|---|
| D1 | Worktree created from base 53e22b67; read CLAUDE.md, ledger, migration design, C-line contracts/tests/visualization sources, old geoviz seismic panel semantics | Worktree HEAD = 53e22b67, clean; base interfaces sufficient, no C-line extension needed | pass | publish headers + v3-contracts.md |
| D2 | Published public headers (color_maps / slice_selection / slice_controller / seismic_slice_widget) + v3-contracts.md + first commit | Commit `57df6587646f53c2e7db33ba36a68dd9140ae43c` | pass | implementation |
| D3 | Full implementation: colormap LUTs, Qt-free SliceController (serialized worker, 1-queued+1-in-flight coalescing, generation/epoch staleness, LRU plane cache), SeismicSliceWidget host (axis/index/colormap/range/zoom/pan, frozen orientation, selection events with time-depth policy), example consumer; 5 test executables + CMake | g++ -fsyntax-only clean on every TU (light checks, outside the heavy slot) | pass (source-level) | gated configure/build/ctest |
| D4 | Gated configure + build (Qt 6.11.2/GCC 16.2.1/Ninja/Release): 18/18 targets link clean; first ctest 4/5 | `seismic_viewer.widget` failed: initial colormap combo index mismatched `color_map_name` ("grayscale" shown, "seismic" set) → ctor now syncs combo to "seismic" | fail → fixed | retest |
| D5 | Retest after fix; next failure: range test's wait predicate was indistinguishable between old/new stretch (pixel (0,0)==0 in both) → wait on the only differing pixel (0,1) | 5/5 groups up to zoom test | fail → fixed | retest |
| D6 | Zoom/pan test used offsets outside the clamp envelope of a tiny 8x32 image → test now uses in-bounds offsets and asserts the exact clamp edges (width-8/height-8); scale clamps [1,64] verified | source-swap + 20-cycle tests PASS | fail → fixed | retest |
| D7 | Heartbeat test arithmetic error (120 ms read can host ~12 beats of a 10 ms timer, asserted ≥20) → read delay raised to 300 ms (≥30 beats possible) | — | fail → fixed | gated retest (blocked once: A-line held the shared slot; waited per protocol) |
