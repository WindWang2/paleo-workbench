# CI merge policy

Last updated with issue **#234** (post Well Log Workstation / engine PR #233).

## Product merge gates (required)

A PR is merge-ready when these are green on the head SHA:

| Gate | Workflow / job |
|------|----------------|
| **WellLogEngine C++ (Ubuntu)** | `WellLogEngine C++` — shared ON/OFF, ASan, Qt Mesa, wheels, vcpkg, benchmark as configured |
| **Well Log Workstation (host)** | `CI` → `Well Log Workstation (host)` (3.12 + 3.13) |
| **Merge gate (workstation host)** | `CI` → `Merge gate (workstation host)` (aggregates host matrix) |

Cross-workflow: GitHub does not `needs:` across workflows; reviewers confirm **WellLogEngine C++** on the same commit as the CI host gate.

## Advisory (not a merge blocker)

| Job | Notes |
|-----|--------|
| **Tests (Python *) [advisory]** | Full monorepo suite. `continue-on-error: true`. Completes after hang fix; remaining known failures are `xfail` via `tests/advisory_xfail.py` (#234). |

Do **not** block merge solely on advisory red. Prefer fixing or adding an entry in `tests/advisory_xfail.py` with a reason pointing at #234 or a dedicated ticket.

## Windows WellLogEngine

**Status (as of #234 / PR #235):** matrix row **deferred** (Ubuntu-only `os`) until Actions can finish a full Windows ctest. Code for Windows is staged:

- Text-linked tests gated with `if(WELLLOG_BUILD_TEXT)` (multi-scale, PDF scene, export-parity).
- MSVC portability: `std::numbers::pi_v` (no `M_PI`), `_popen`/`_pclose`, C4251/C4275 suppress, shadow renames (C4456), `WELLLOG_SCENE_API` on multi-well friends.
- Workflow helpers: zlib prefix, empty `VCPKG_ROOT` ignored, MSVC `Werror` OFF, Ninja path after `msvc-dev-cmd`.
- Re-enable: set `os: [ubuntu-latest, windows-latest]` in `well-log-engine.yml` and re-run.
- **Python wheels remain Ubuntu-only** (Shiboken6/Qt aqt on Windows still open).

## Hang prevention

- Prefer stubbing **all** `QMessageBox` / modal dialogs in headless tests.
- Per-test: `--timeout-method=thread` on monorepo and workstation jobs.
- Outer suite ceiling remains as a backstop for native hangs.

## Related

- Issue #234 — Windows CI + advisory suite cleanup
- PR #233 — Well Log Workstation phase-1 + engine bridge
- Map #207 — wayfinder product map (closed)
