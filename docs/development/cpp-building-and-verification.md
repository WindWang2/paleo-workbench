# Building and verifying the C++ migration locally

This is the practical guide for the engineering side of the Python -> C++20/Qt6/QGIS
conversion: how to configure, how to build **one** slice instead of the whole tree, how to
replay the Python oracle, how to smoke the native product, and how to keep seven parallel
worktrees from running the machine out of memory.

It is written against the tooling on `main`:

| Tool | Purpose |
| --- | --- |
| `cmake/PwbFeatures.cmake` | Declares every `PWB_BUILD_*` switch, resolves implied/required edges, prints the resolved graph |
| `CMakePresets.json` | Low-resource configure/build/test presets (`developer-fast`, `conversion-kernel`, `low-memory`, `native-product-smoke`, ...) |
| `tools/verify/pwb_local_verify.py` | The single local verification driver |
| `scripts/cpp-migration/Invoke-ResourceGate.ps1` / `invoke-resource-gate.sh` | Cross-worktree admission gate (one heavy build slot, RAM floor, job cap) |
| `tools/migration/pwb_migration_inventory.py` | Generated Python -> C++ migration inventory |
| `tools/verify/pwb_artifact_hygiene.py` | Build-artifact / fixture hygiene audit |
| `tools/migration/pwb_python_dependency_audit.py` | Python-runtime dependency audit |

No step in this document waits on online CI. Local verification is the acceptance signal.

---

## 1. Resource discipline with seven parallel worktrees

Seven worktrees build the same repository at the same time. Compiler memory, not CPU, is the
scarce resource, and a single runaway `-j$(nproc)` link step can evict every other worktree.

Hard rules:

* **One heavy build per worktree at a time.** The shared lock lives in the *common* git dir
  (`cpp-migration-heavy.lock`), so it is enforced across all worktrees, not just within one.
* **Job caps.** `CMAKE_BUILD_PARALLEL_LEVEL` / `CTEST_PARALLEL_LEVEL` default to `2`. The
  driver hard-caps at `8` and clamps anything above it with a warning.
* **No unbounded parallelism.** Never pass `-j$(nproc)`, `--parallel` with no value, or start
  two full-tree builds.
* **Prefer targeted builds.** `--targets <one library or test>` rebuilds incrementally; a full
  tree rebuild is almost never what you want while six other worktrees are live.
* **Serialise high-memory configurations.** Debug + ASAN and the QGIS-heavy platform closure
  should run one at a time and alone.
* **Lower the RAM floor when you know the machine is loaded.** The driver refuses to start
  below `--min-free-gib` (default `4.0`). When free RAM drops because other worktrees are
  building, pass a smaller floor for *small* targets rather than disabling the check, e.g.
  `--min-free-gib 2.5 --targets mapping_kernel.ring_ops`.
* **Rebuild vendored QGIS as rarely as possible.** Configure `PWB_BUILD_PLATFORM=OFF` for
  kernel work — that is exactly what `developer-fast` and `conversion-kernel` do.

### Using the shared gate

Everything heavy can be wrapped by the admission gate, which returns `75` when the slot is
taken or RAM is short:

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cpp-migration\Invoke-ResourceGate.ps1 `
    -Action Probe
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cpp-migration\Invoke-ResourceGate.ps1 `
    -Action Configure -SourceDir . -BuildDir build\presets\developer-fast -Configuration Debug `
    -CmakeArguments -DPWB_BUILD_PLATFORM=OFF,-DPWB_BUILD_DATA=ON
```

```bash
# POSIX
scripts/cpp-migration/invoke-resource-gate.sh Probe
scripts/cpp-migration/invoke-resource-gate.sh Configure -s . -b build/presets/developer-fast -c Debug
```

Gate exit codes (identical on both platforms):

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | internal / environment error (for example: build dir not configured yet) |
| `64` | invalid usage (bad flag, non-numeric threshold) |
| `75` | resource refusal — another job holds the slot, or free RAM is below the floor |
| `124` | reserved for a future timeout; never emitted today |

Diagnostic tokens are stable and machine-readable: `RESOURCE_READY`,
`RESOURCE_BUSY`, `RESOURCE_LOW_MEMORY`, `RESOURCE_STALE_LOCK_RECOVERED`,
`RESOURCE_GATE_WARNING`, `RESOURCE_GATE_ERROR`.

A lock whose owner process is gone and whose sidecar is older than
`-StaleLockMinutes` (default `45`) is reclaimed automatically; a live owner is never
reclaimed. `-ForceRecoverLock` overrides the age check but still refuses to steal from a
running process.

### Self-tests for the gate

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cpp-migration\Test-ResourceGate.ps1
bash scripts/cpp-migration/test-resource-gate.sh
```

Both cover: probe success, concurrent busy, low memory, stale-lock recovery, job clamping,
invalid usage, and "Build refused because the build dir is not configured".

---

## 2. The local verification driver

`tools/verify/pwb_local_verify.py` is the one entry point. Every command is low-resource by
default and never touches the network.

```bash
python tools/verify/pwb_local_verify.py doctor          # toolchain, SDK, RAM, gate presence
python tools/verify/pwb_local_verify.py presets         # CMakePresets sanity
python tools/verify/pwb_local_verify.py configure --preset developer-fast
python tools/verify/pwb_local_verify.py build --preset developer-fast --targets <target>
python tools/verify/pwb_local_verify.py test  --preset developer-fast -R <regex>
python tools/verify/pwb_local_verify.py oracle --unit mapping_kernel
python tools/verify/pwb_local_verify.py smoke --preset native-product-smoke
python tools/verify/pwb_local_verify.py inventory
python tools/verify/pwb_local_verify.py hygiene
python tools/verify/pwb_local_verify.py pyaudit
python tools/verify/pwb_local_verify.py all --preset developer-fast
```

Useful flags: `--jobs N` (1..8, default 2), `--min-free-gib`, `--config`, `--timeout`,
`--python <interpreter>`, `--targets a b c`, `-R <regex>`, `--replay`.

### Why the driver knows about the toolchain

Two failures cost real time on a fresh shell and the driver removes both:

1. **`vcvars64.bat` / `Enter-VsDevShell` do not work** in a sandbox that blocks `reg.exe`.
   They locate the Windows SDK through the registry and die with a misleading
   `RC Pass 1 ... failed` plus `CMAKE_MT-NOTFOUND`, while `cl.exe` still compiles fine.
   The driver discovers MSVC, the Windows SDK and Ninja by directory scan and passes
   `CMAKE_C_COMPILER`, `CMAKE_CXX_COMPILER`, `CMAKE_RC_COMPILER` and `CMAKE_MT` explicitly.
2. **The data oracle gate needs `pydantic`.** `tests/cpp/data` refuses to configure unless the
   interpreter CMake finds can `import pydantic`. A linked worktree has no `.venv` of its own,
   so the driver falls back to the principal worktree's `.venv` (found via the `.git` file).
   Override with `--python <path>` or `PWB_PYTHON=<path>`.

If neither is set up, `doctor` says so before you waste a configure.

---

## 3. Configure presets

| Preset | Closure | Use it for |
| --- | --- | --- |
| `developer-fast` | platform OFF, data ON, mapping kernel + a few slices | the tight edit/compile/test loop; no QGIS SDK needed |
| `conversion-kernel` | every Qt-free/QGIS-free CONV slice + tests | checking a kernel port against its oracle |
| `native-product-smoke` | platform + data + science + integration tests | the product closure; heavy, run alone |
| `low-memory` | `conversion-kernel` with one job, Release | when other worktrees are building |
| `windows-msvc` / `linux-ninja` | full native closure per platform | platform-specific builds |
| `windows-msvc-debug/-release`, `linux-gcc-release` | the original CPP-A presets | unchanged, kept for compatibility |

All presets pin `CMAKE_BUILD_PARALLEL_LEVEL=2` and `CTEST_PARALLEL_LEVEL=2` through their
`environment` block, so the cap survives even when a nested tool would fan out.

Validate the preset file whenever you touch it:

```bash
python tools/verify/pwb_local_verify.py presets
```

It checks that every build/test preset points at a real configure preset, that no preset asks
for more than 8 jobs, and that the documented preset names all exist. It also warns — without
failing — when presets share a `binaryDir`, because that silently reuses another preset's
CMake cache. The three original CPP-A presets share `build/cpp-platform` on purpose; new
presets use `build/presets/<name>`.

---

## 4. Building one CONV slice

Each slice is an opt-in switch that adds sources to an existing library. Turning a slice on
implies whatever it needs, and asking for a slice whose dependency is off fails at configure
time instead of building a half-tree:

```bash
python tools/verify/pwb_local_verify.py configure --preset developer-fast
python tools/verify/pwb_local_verify.py build --preset developer-fast \
    --targets mapping_kernel.ring_ops
```

To add a slice that is not in the preset, configure with the switch explicitly:

```bash
python tools/verify/pwb_local_verify.py configure --build-dir build/presets/conv22 \
    --cache-var PWB_BUILD_DATA=ON --cache-var PWB_BUILD_CONV_22=ON
```

`PWB_BUILD_CONV_22=ON` pulls in `CONV-12` and `CONV-19` automatically, and the feature summary
prints why each switch is on:

```
--   ON   PWB_BUILD_CONV_22  [declared]
--   ON   PWB_BUILD_CONV_12  [implied-by:PWB_BUILD_CONV_22]
```

Reconfigure with `--verbose` to list the switches that are off.

---

## 5. Running the Python oracle

The conversion rule is that Python behaviour is the truth and C++ must match it. Every
important port ships a frozen fixture plus the generator that produced it.

Find the oracle for a unit:

```bash
python tools/verify/pwb_local_verify.py oracle --unit mapping_kernel
```

This prints, per unit, the repository path of the C++ sources, the generator script, the
frozen fixture, and which recorded Python origins still exist. Add `--replay` to actually
re-run the generators (that needs the product virtualenv, because the generators import the
real Python implementation).

Run the C++ side against the frozen fixture:

```bash
python tools/verify/pwb_local_verify.py test --preset developer-fast -R ring_ops
```

`ctest` is invoked with `--no-tests=error`, so "no tests matched" can never be mistaken for a
pass. When a kernel changes semantics, regenerate the fixture *and* record the deviation in the
slice's findings — never hand-edit a fixture to make a test go green.

A generator that emits a `.inc` table into a source directory (for example
`libs/factor_fusion/src/factor_units_data.inc`) must be regenerated by its script, not edited.
`pwb_artifact_hygiene.py` reports these generator -> generated-file pairings.

---

## 6. Native product smoke

```bash
python tools/verify/pwb_local_verify.py configure --preset native-product-smoke
python tools/verify/pwb_local_verify.py build --preset native-product-smoke
python tools/verify/pwb_local_verify.py smoke --preset native-product-smoke
```

Smoke runs the built binary with `QT_QPA_PLATFORM=offscreen` and reports the exit code. A
negative exit code is a crash; a plain non-zero exit from an offscreen run is not necessarily a
failure, but it must be explained, not ignored. If no product binary exists yet, smoke reports
`SKIPPED` rather than pretending to pass.

---

## 7. Packaging

The packaging skeleton is opt-in and off by default:

```bash
python tools/verify/pwb_local_verify.py configure --build-dir build/presets/pkg \
    --cache-var PWB_ENABLE_PACKAGING=ON
cmake --install build/presets/pkg --prefix build/stage
```

With `PWB_ENABLE_PACKAGING=OFF` (the default) no install rule is created at all, so the other
worktrees cannot be affected. The installed layout, the Qt plugin deployment, the Windows DLL
collection and the Linux RPATH placeholder are described in `cmake/PwbInstall.cmake`. The
`pwb-diagnose` target prints the resolved resource and runtime-directory search paths.

---

## 8. Cleaning build trees

Build trees live under `build/` and are git-ignored. Prefer deleting one preset at a time:

```bash
rm -rf build/presets/low-memory          # reconfigure needed; sources untouched
cmake --build build/presets/developer-fast --target clean   # keep the cache
```

Do not delete another worktree's `build/` directory: with seven worktrees sharing one disk and
one memory budget, a concurrent full rebuild is exactly the load spike the gate exists to
prevent. If a build directory is corrupt, remove only that preset's directory and reconfigure.

`PWB_SUBDIR_ADDED_*` cache entries and the resolved feature graph live in `CMakeCache.txt`; a
stale cache from a different feature set is the usual cause of "my switch is on but nothing
built". Reconfigure with `--preset` (which carries the same cache variables) rather than
editing the cache by hand.

---

## 9. Auditing the conversion state

```bash
python tools/migration/pwb_migration_inventory.py \
    --json-out build/migration-inventory/inventory.json \
    --markdown-out docs/development/cpp-migration-inventory.md
python tools/verify/pwb_artifact_hygiene.py
python tools/migration/pwb_python_dependency_audit.py
```

The inventory is generated from repository facts — CMake options, `libs/*` trees, the Python
origins recorded in C++ headers, frozen fixtures and application wiring. It classifies every C++
unit (native complete + wired, native core not wired, partial native, Python-only production,
oracle/test-only Python, legacy candidate) and it never needs hand maintenance. The committed
Markdown snapshot is a generated artifact: re-run the generator instead of editing it.
