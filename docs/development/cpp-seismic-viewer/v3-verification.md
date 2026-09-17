# CPP-D v3 Verification — Seismic 2-D Slice Viewer

All commands below were actually executed on this host (Linux mirror of the
repo, 16 hw threads, 62 GiB RAM); exit codes are quoted. Build/test runs went
through the shared heavy-slot gate semantics (see §1).

## 0. Identities

- Branch: `codex/cpp-v2-seismic-viewer`; worktree `.worktrees/cpp-v2-seismic-viewer`; base `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf` (verified ancestor: worktree created from it).
- Commits: `57df6587646f53c2e7db33ba36a68dd9140ae43c` (public headers + v3-contracts.md), `252c0cf0b015d09cfcb89a71dbe733fb4031036f` (implementation + tests + example green), plus the final docs commit.
- Toolchain: GCC 16.2.1 / Clang 22.1.8, CMake 4.4.3, Ninja, C++20, Qt **6.11.2** system SDK (`/usr/lib/cmake/Qt6`; qmake6 reports 6.11.2). A's Windows Qt 6.8.0/MSVC manifest does not exist on this host — the system SDK is a real, verifiable Qt (not Conda/PySide); Windows ABI conformance stays with A.

## 1. Resource gate (honest deviation, semantics preserved)

`pwsh` is not installed on this Linux host, so `scripts/cpp-migration/Invoke-ResourceGate.ps1`
cannot run unmodified. Its semantics were reproduced 1:1 with a local flock
wrapper (`/tmp/pwb_gate_eq.sh`, kept out of the repo):

| Gate rule | PowerShell original | Equivalent used | Observed |
|---|---|---|---|
| exclusive shared slot | `FileShare.None` open of `<git-common-dir>/cpp-migration-heavy.lock` | `flock -x` on the same file | cross-line contention with the A-line (platform worktree) hit twice → D waited, exit 75 honored, no foreign process touched |
| memory floor | `Win32_OperatingSystem.FreePhysicalMemory ≥ 8 GiB` | `/proc/meminfo MemAvailable` | 52.87–53.11 GiB each acquisition |
| jobs | `CMAKE_BUILD_PARALLEL_LEVEL=2`, `CTEST_PARALLEL_LEVEL=2`, OMP/BLAS/MKL/NUMEXPR=1 | identical env exports | — |
| build location | must be under `<worktree>/build` | identical (build dirs: `build/cpp-seismic-viewer{,-notests,-asan,-asan-clang}`) | — |
| no silent empty suites | `ctest --no-tests=error --timeout 180` | identical flags | — |

## 2. Configure / build (gated, exit 0)

```
cmake -S libs/seismic_viewer -B build/cpp-seismic-viewer -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpp-seismic-viewer --parallel 2
```
- Configure exit 0 (`Found Qt6 6.11.2`, GCC 16.2.1, Ninja). `Pwb::Visualization` was pulled from the same checkout (no target pre-existed) — no source copied.
- Build exit 0: 18/18 steps, targets `pwb_visualization`, `pwb_seismic_viewer` (alias `Pwb::SeismicViewer`), `seismic_viewer_example`, 5 test executables. Zero warnings under `-Wall -Wextra -Wpedantic`.

## 3. Mandatory tests (`ctest`, gated, `--no-tests=error`)

`ctest -N` lists exactly five tests, all `seismic_viewer.*`, none skipped:
`seismic_viewer.contracts`, `.controller`, `.render`, `.widget`, `.performance`.

| Run | Command | Result |
|---|---|---|
| pass 1 | `ctest --test-dir build/cpp-seismic-viewer --parallel 2 --output-on-failure --no-tests=error --timeout 180` | **5/5 passed** (exit 0) |
| pass 2 (final chain re-run, after a cosmetic label fix) | same | **5/5 passed** (exit 0) |

Per-test contents (11 + 9 + 5 + 11 + 2 = 38 registered cases, zero skips):
- `contracts` (11): colormap registry/endpoints/polarity, unknown-map no-op, unit-kind policy, selection vocabulary, stats vocabulary, cache-capacity clamp end-to-end.
- `controller` (9): fresh-plane byte identity; barrier-window coalescing (30 submits → ≤3 reads, ≥26 merges); **late-result-cannot-overwrite-new-source** (slow A in flight, swap to B, every delivered plane carries the new epoch, delivered bytes == B's plane); strictly serialized reads (`overlapped_reads()==0`); visible failure + recovery; null/empty/out-of-bounds diagnostics; bounded LRU (peak ≤ cap, exact hit counts); shutdown quietness (no sink calls after `request_shutdown()` returns); explicit range re-colorizes from cache (0 new reads).
- `render` (5): three-axis planes byte-equal to the frozen `tiny_sgy` oracle (`expected_inline/crossline/sample.f32`); inline indexed8 byte-equal to `expected_inline_indexed8.f32` + explicit-range restretch; asymmetric 5×3×17 permuted-strides planes exact + negative-step extents; constant/all-NaN degeneracy flagged with all-zero plane and retained diagnostic; NaN→0 and 127.5→127 truncation per frozen oracle; degenerate explicit range visible.
- `widget` (11, offscreen `QT_QPA_PLATFORM=offscreen`): visible states (`no_source/empty/degenerate/failed→ok` recovery); **frozen orientation pixel audit** (image dims per axis; inline `pixelIndex(x,y)` == oracle indexed8 transposed; crossline/sample value lookups exact); asymmetric physical coordinates/units incl. negative sample step; **real child controls** (slider/axis combo/cmap combo drive real requests; cmap swap = 0 new reads); explicit-range pixel restretch + invalid-range no-op + reset; zoom/pan clamps (scale ∈ [1,64], offsets to image edges); selection events (origin/revision/axis/index/coordinates/units; time-range order; `not_convertible` without relation, `converted` m with `LinearTimeDepth`); echo suppression + external apply never re-emits + stale-revision/foreign-volume rejection; source swap while A is in flight → B's geometry displayed, `discarded_stale ≥ 1`; **20× open/swap/close cycles** (incl. delete during in-flight reads) with no hang and no post-delete callbacks; **GUI heartbeat** (300 ms read, 10 ms timer → ≥20 beats while the slice is produced); screenshots saved.
- `performance` (2): see §5.

Fixture discipline: frozen oracle consumed read-only from
`tests/cpp/science/fixtures/seismic/tiny_sgy/`; new data only under
`tests/cpp/seismic_viewer/fixtures/` (currently README-only — all synthetic
patterns are generated in-test, deterministic). **No Python in production
paths**; the manifest/f32 reader is C++.

## 4. Consumption variants

- `BUILD_TESTING=OFF` + `PWB_SEISMIC_VIEWER_BUILD_TESTS=OFF` → configure exit 0, build exit 0, `seismic_viewer_example` produced and executed (`--self-check` exit 0, screenshot saved): production target fully usable without tests.
- Example self-check (frozen fixture, offscreen): `seismic_viewer_example --self-check --fixture tests/cpp/science/fixtures/seismic/tiny_sgy --output .../example_selfcheck.png` → `self-check: state=3(ok) saved=1`, exit 0.

## 5. Performance report (fixed medium volume)

Volume 256×256×512 float32 (128.0 MiB), inline plane 131,072 floats (512 KiB),
Release build, 16 hw threads, in-memory backend (timings include `read_slice` +
`map_slice_to_indexed8`, **no disk I/O**), cache = 4 planes:

- slice submit→deliver: **p50 = 0.483 ms, p95 = 0.600 ms** (n = 60 distinct planes)
- memory: RSS +128.2 MiB for the volume body itself; process VmHWM 187 MiB (incl. Qt + test harness)
- interaction storm: **150 index moves submitted in 0.003 ms → 1 executed read, 149 coalesced, elements_read = 131,072 = exactly one plane** (volume = 33,554,432 elements) — no per-interaction whole-volume copy, pending work bounded (≤1 queued + 1 in-flight), plane-cache peak ≤ 4.

## 6. Sanitizer evidence

- GCC `-fsanitize=address,undefined` + full LSan: `seismic_viewer.contracts`, `.controller`, `.render`, `.performance` all pass with **zero suppressions** — the Qt-free core is leak-clean.
- Clang 22 `-fsanitize=address,undefined` + LSan: `seismic_viewer.widget` **11/11 passed** and `seismic_viewer.controller` 9/9 passed. LSan reports `Suppressions used: 21 (1736 bytes) — template fcitx`: the desktop fcitx5 input-method plugin (loaded by offscreen QApplication) allocates DBus objects that outlive `main()`; every suppressed stack is pure fcitx/Qt6DBus (no `pwb` frame). No product allocation is whitelisted anywhere. GCC's libasan rejects `leak:` suppressions, hence the Clang variant for the widget group.

## 7. Screenshot evidence

- `build/cpp-seismic-viewer/seismic_viewer_tests/seismic_viewer_inline.png` (18,264 B): tiny_sgy inline slice 3, seismic colormap, overlay range badge = the frozen oracle stretch (−2.167734…2.459896), coordinate label "Inline 4" (= origin 1 + 3·step 1).
- `build/cpp-seismic-viewer/seismic_viewer_tests/seismic_viewer_operated.png` (15,946 B): after real operation trail (axis switch → sample, index 16, grayscale, explicit range, zoom 3×/pan).
- `build/cpp-seismic-viewer-notests/example_selfcheck.png` (19,108 B): the standalone production consumer embedding the widget on the frozen fixture.

## 8. Not executed / known limitations

- No Windows/MSVC build on this host (Linux mirror; A-line territory).
- No real SEG-Y/Zarr backend parsing (out of scope this round by prompt; the in-memory/owning backends and any future chunked backend implementing `ISeismicVolume` plug in unchanged).
- `chunk_plan()` is consumed nowhere yet (chunked store is future work; interface reserved).
- The `seismic` colormap center is white by construction; polarity conventions (positive red vs blue) are a host preference A may flip later by swapping control points — frozen for v3.
- Widget drag-selection supports time intervals on section views only (sample-slice drag selects nothing) — documented, tested, deliberate.
