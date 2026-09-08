# Audit — building/running the vendored QGIS + qgis_render_bridge on THIS Windows machine

Date: 2026-09-08. Scope: evidence only; nothing was built and no repo file was
modified except this document. Worktree under audit:
`C:\Users\wangj.KEVIN\projects\paleo-workbench\.worktrees\qgis-geolayer-cartography-v7`
(hereafter `<wt>`). Machine: Windows 11 (10.0.26200), 32 GB RAM
(33,492,422,656 B), C: ~1.2 TB free, D: ~115 GB free.

---

## 1. What the build actually does (from `native/qgis_render_bridge`)

### setup.py (opt-in pybind11 extension)

- Gate: `PALEO_WITH_QGIS_RENDERER` in {1,true,yes,on} (setup.py:23-29).
- Vendor source: `<repo>/third_party/qgis` (setup.py:20). Vendor build dir:
  `PALEO_QGIS_BUILD_DIR` or default `native/qgis_render_bridge/build/qgis-vendor`
  (setup.py:60-62).
- Done-artifact test on win32 (setup.py:65-72, 88-112):
  `output/lib/qgis_core.lib` + `output/lib/qgis_gui.lib` +
  `output/lib/qgis_analysis.lib` + `resources/srs.db`.
- `PALEO_QGIS_REUSE_VENDOR=1` (setup.py:75-85): links an existing completed
  vendor build without reconfiguring — designed for cross-worktree reuse
  ("rebuilding QGIS per worktree is exactly what the build-budget rules
  forbid").
- Fresh vendor build (setup.py:171-227) runs exactly:

  ```
  cmake -S third_party/qgis -B <build_dir> -G Ninja -DCMAKE_BUILD_TYPE=Release
        -DWITH_PYTHON=OFF -DWITH_BINDINGS=OFF -DWITH_DESKTOP=OFF
        -DWITH_QGIS_PROCESS=OFF -DWITH_3D=OFF -DWITH_GUI=ON -DWITH_ANALYSIS=ON
        -DWITH_AUTH=ON -DWITH_CRASH_HANDLER=OFF -DWITH_SERVER=OFF
        -DWITH_CUSTOM_WIDGETS=OFF -DWITH_QUICK=OFF -DWITH_QTWEBENGINE=OFF
        -DWITH_QTPOSITIONING=OFF -DWITH_PDAL=OFF -DWITH_DRACO=OFF
        -DWITH_QTSERIALPORT=OFF -DWITH_INTERNAL_SPATIALINDEX=ON
        -DUSE_OPENCL=OFF -DENABLE_TESTS=OFF -DENABLE_LOCAL_BUILD_SHORTCUTS=ON
        -DUSE_CCACHE=OFF -DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE
        -DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=FALSE
        [-DCMAKE_PREFIX_PATH=<prefix>]   # from PALEO_QGIS_CMAKE_PREFIX or CMAKE_PREFIX_PATH
  cmake --build <build_dir> --target resources qgis_core qgis_gui qgis_analysis --parallel <jobs>
  ```

  `jobs` = `PALEO_QGIS_BUILD_JOBS`, **default 2**. So the bridge builds the
  FULL `qgis_core` + `qgis_gui` + `qgis_analysis` shared libraries plus the
  `resources` target (which generates `resources/srs.db` via QGIS's crssync,
  needing live PROJ+SQLite at build time) — a reduced *option set*, not a
  reduced source set.
- Extension itself (setup.py:238-276): 7 TUs
  (`qgis_render_bridge.cpp, style_codec.cpp, gui_service.cpp,
  geometry_service.cpp, map_stack_service.cpp, edit_tools.cpp, bindings.cpp`),
  `"/O2", "/std:c++20"` on win32, links the three qgis `.lib`s directly plus
  `libraries=["Qt6Svg", "Qt6PrintSupport"]` (no `library_dirs` passed — see
  §6 B4), macro `PALEO_QGIS_PREFIX_PATH="<build_dir>/output"` baked in for
  runtime resource lookup. `python_requires=">=3.12,<3.14"` — worktree venv is
  3.12.13, OK.
- Qt headers for the extension (setup.py:32-57): `PALEO_QGIS_CMAKE_PREFIX`
  (or first entry of `CMAKE_PREFIX_PATH`) must contain
  `include/qt6` + subdirs `QtCore QtGui QtWidgets QtXml QtSvg QtPrintSupport`;
  otherwise it shells out to `pkg-config` (**no pkg-config exists on this
  machine** — the env-var route is mandatory on Windows).
- `pyproject.toml` (build-system): `requires = ["setuptools>=64",
  "pybind11>=2.12"]` — an isolated PEP 517 build fetches pybind11 itself.
- `CMakeLists.txt` (bridge) mirrors the same ExternalProject vendor build
  (same flags, targets `resources qgis_core qgis_gui qgis_analysis`) and is
  only used for the standalone C++ selftest; the Python path is setup.py.

### Vendored QGIS (`third_party/qgis`) — provenance and requirements

- `UPSTREAM.md`: QGIS **4.2.0**, tag `final-4_2_0`, commit
  `ca5812c8b8e39b59695a3b0206fc5f3206eda0a9`. Only `CMakeLists.txt` differs
  from upstream (drops `doc/i18n/postinstall/linux` subdirs); one compat
  patch in `src/core/qgsconnectionpool.h` (Qt < 6.6 fallback — irrelevant at
  Qt 6.11). Committed content, not a git submodule (no init needed).
- Top-level `CMakeLists.txt` hard requirements given the bridge's flags:

  | Requirement | Evidence (vendored CMakeLists.txt) | Status for us |
  |---|---|---|
  | CMake ≥ 3.22, C++20 | :3, :80 | cmake 4.4.2 available |
  | FLEX ≥ 2.6, BISON ≥ 2.4 (REQUIRED) | :414-415 | **missing** → conda `winflexbison` |
  | PROJ ≥ 8.1 REQUIRED | :436-440 | conda `proj` (9.8.0 exists locally) |
  | GEOS REQUIRED | :442 | conda `geos` (3.14.1 locally) |
  | GDAL REQUIRED | :444 | conda `gdal` (3.12.2 locally) |
  | EXPAT REQUIRED | :446 | conda `libexpat` |
  | spatialindex | :447-451 | internal (`WITH_INTERNAL_SPATIALINDEX=ON`) |
  | LibZip REQUIRED (`zip` lib) | :457; cmake/FindLibZip.cmake:36 | **missing** → conda `libzip` |
  | nlohmann_json REQUIRED | :458-459 | internal copy (`PREFER_INTERNAL_LIBS`) |
  | Sqlite3 REQUIRED | :465 | conda `sqlite` |
  | Protobuf + protoc REQUIRED | :467-473 | **missing** → conda `libprotobuf`+`protobuf` |
  | ZLIB REQUIRED | :474 | conda `zlib` |
  | exiv2 REQUIRED (`WITH_EXIV2` default ON) | :23, :477-480 | **missing** → conda `exiv2` |
  | Qt6 ≥ 6.4: Core Gui Widgets Network Xml Svg Concurrent **Test** Sql | :584-589 | **missing** → conda `qt6-main` |
  | Qt6 **Core5Compat** REQUIRED | :618 | part of conda `qt6-main` (CI-proven) |
  | Qt6 **Sql**Private REQUIRED when Qt ≥ 6.9 | :619-622 | conda `qt6-main` ships private headers (CI-proven on Linux) |
  | Qt6 PrintSupport REQUIRED (`WITH_QTPRINTER` default ON) | :624-633 | conda `qt6-main` |
  | Qt6 **Multimedia MultimediaWidgets Qml QuickWidgets UiTools** REQUIRED — unconditional in `src/gui/CMakeLists.txt:1864` | gui | conda `qt6-main` + `qt6-multimedia` |
  | Qt6 SvgWidgets REQUIRED | `src/gui/CMakeLists.txt:2044` | conda `qt6-main` |
  | QScintilla REQUIRED (WITH_GUI=ON) | :665-666; FindQScintilla names `qscintilla2-qt6`/`qt6scintilla2`/… | **missing** → conda `qscintilla2` (layout verify) |
  | Qwt ≥ 6.2 | :668-684 | auto-falls back to internal `external/qwt-6.3.0` |
  | **Qt6Keychain CONFIG REQUIRED** | :688 | **missing** → conda `qtkeychain` (CMake config verify) |
  | **QCA** REQUIRED (WITH_AUTH=ON; names `qca-qt6`…) | :691-693 | **missing** → conda `qca` |
  | SpatiaLite REQUIRED (`WITH_SPATIALITE` default ON, not disabled by bridge) | :530-533 | conda `spatialite` (present in local "gdal" env) |
  | ZSTD REQUIRED (`WITH_EPT` default ON) | :550-553 | conda `zstd` (present locally) |
  | GSL REQUIRED (`WITH_GSL` default TRUE + WITH_ANALYSIS=ON) | :927-933 | **missing** → conda `gsl` |
  | PostgreSQL | :518-520 (optional find) | conda `postgresql` or let it not-found |
  | Python ≥ 3.11 interpreter | :949-956 | venv 3.12.13 |
  | MSVC supported (`/utf-8 /permissive-`, 8 MB stack) | :909-918 | MSVC 14.38 present |

- Optional and default-off for us: PDAL/Draco/SerialPort/Positioning/WebEngine/
  Quick/3D/Server/Desktop/Process/crash-handler are all OFF via bridge flags.

## 2. Prior build knowledge in-repo (what previous goals actually ran)

**There has never been a Windows vendor build.** All documented builds are
Linux (CI) or WSL (v5-era machine). Evidence:

1. `.github/workflows/qgis-renderer.yml` (dedicated CI leg, ubuntu-latest,
   `timeout-minutes: 120`):
   - Header: vendored QGIS is "a ~20-60 min ninja build"; a step comment says
     "before the ~50 min vendored QGIS build".
   - apt list (32 packages): `qt6-base-dev libqt6svg6-dev qt6-5compat-dev
     qt6-multimedia-dev qt6-declarative-dev qt6-tools-dev libqca-qt6-dev
     libsqlite3-dev libexpat1-dev libproj-dev libgeos-dev libgdal-dev
     libgsl-dev libpq-dev libzip-dev libzstd-dev zlib1g-dev libbz2-dev
     libspatialite-dev libqt6opengl6-dev libqt6concurrent6 libprotobuf-dev
     protobuf-compiler libqscintilla2-qt6-dev qtkeychain-qt6-dev libexiv2-dev
     bison flex build-essential cmake ninja-build`.
   - The Qt-runtime trick (this is the key precedent for Windows): a conda env
     provides python 3.12 + `pyside6=6.11.1` + `qt6-main=6.11.1` +
     `qt6-multimedia=6.11.1` in ONE prefix; build runs with
     `CMAKE_PREFIX_PATH=/tmp/qgisqt`, `PKG_CONFIG_PATH=/tmp/qgisqt/lib/pkgconfig`,
     `PALEO_QGIS_BUILD_JOBS: "4"`; runtime prepends the prefix's `lib` to
     `LD_LIBRARY_PATH` so ONE Qt set (Core5Compat included) serves both the
     bridge and PySide6. Header explicitly rules out aqtinstall ("upstream
     repo metadata no longer parses") and pip PySide6 wheels ("bundle no
     Core5Compat").
   - Build command: `PALEO_WITH_QGIS_RENDERER=1 … /tmp/qgisqt/bin/python -m
     pip install -e native/qgis_render_bridge`; then import smoke
     `python -c "import qgis_render_bridge; …"`, vendor-integrity test, and
     `PALEO_REQUIRE_QGIS=1 QT_QPA_PLATFORM=offscreen pytest -m qgis tests/`
     with a ≥9-passed count gate.
2. `docs/development/qgis-geology-production-v5/baseline.md:51,64-66` and
   `verification.md:7,24`: a completed vendor build existed at
   `/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor`
   (Linux/WSL, "4.2.0, 1.1GB, core/gui/analysis+srs.db 齐全") and was REUSED,
   never rebuilt: `PALEO_WITH_QGIS_RENDERER=1 PALEO_QGIS_REUSE_VENDOR=1
   PALEO_QGIS_BUILD_DIR=<main>/build/qgis-vendor
   PALEO_QGIS_CMAKE_PREFIX=/usr/lib/cmake/Qt6 python3.13 -m pip install -e
   native/qgis_render_bridge`. Bridge-only rebuilds: **~3 min each** (7 TUs,
   -j2), 4 of them during v5. Policy (decisions.md D8): "全部 C++ 编译串行/≤-j2"
   — the -j2 constraint is repo build-budget policy, matching
   `PALEO_QGIS_BUILD_JOBS` default 2. `TEST_INFRA.md` confirms tests ran under
   Linux (`/home/kevin/.conda/envs/paleo312`, PySide6 6.11.2 offscreen).
   Known runtime caveat (decisions.md D7): GeoPDF export returned
   `PrintError(4)` in the offscreen Linux env — capability kept opt-in.
3. ADR 0059 (`docs/adr/0059-qgis-authoring-core.md`): "this machine's gcc 16.x
   ICEs on a few vendored gui TUs; the vendor snapshot builds cleanly with
   clang" (Linux box) and "Local envs must align PySide6's bundled Qt version
   with the system Qt the vendor build links (private `Qt_6_PRIVATE_API`
   symbols are version-checked at load)" — i.e. build against the SAME Qt
   minor version the runtime loads (PySide6's).
4. ADR 0060 (`docs/adr/0060-vendored-gdal.md`): `scripts/build_vendored_gdal.sh`
   (PROJ 9.5.1 + GDAL 3.10.3 superbuild, bash/CMake/Ninja, Linux) is for the
   RUNTIME `osgeo` python bindings — and explicitly: the qgis-renderer CI leg
   "构建 vendored QGIS 时链接系统 libgdal-dev … 与本项目运行时 osgeo 无关" — the
   QGIS C++ build links a normal GDAL dev package, NOT the vendored one. So
   **no Windows vendored-GDAL is a prerequisite for the bridge**.
5. `scripts/build_and_test_windows.ps1` (the Windows pipeline) builds only
   `grid_render_core, layer_model_core, seismic_3d_core, well_log_core,
   geo-viz-engine\native\map_edit_core` with MSVC — `qgis_render_bridge` is
   absent. No Windows counterpart of `build_vendored_gdal.sh` exists.
6. WSL check (this machine, read-only): `wsl -l -v` → `archlinux` (Running),
   `Ubuntu` (Stopped). archlinux has `/home/kevin/projects/paleo-workbench`
   but `native/qgis_render_bridge` contains only `CMakeLists.txt pyproject.toml
   setup.py src` — **no build dir, no srs.db anywhere under /home/kevin**.
   Ubuntu has no `/home/kevin/projects` at all. The v5-era vendor build does
   not exist on this machine; combined with the known-absent Windows builds,
   **reuse is ruled out — a fresh vendor build is required**.

## 3. Toolchain evidence on THIS machine (nothing built)

Present:

- **MSVC**: `vswhere` → `C:\Program Files\Microsoft Visual Studio\2022\Community`
  ("Visual Studio Community 2022"); toolset `14.38.33130`,
  `cl.exe` at `VC\Tools\MSVC\14.38.33130\bin\Hostx64\x64\cl.exe`.
- **CMake/Ninja** (not on bash PATH, but installed):
  `%APPDATA%\Python\Python313\Scripts`: `cmake.exe` **4.4.2**,
  `ninja.exe` **1.13** (this is what `build_and_test_windows.ps1` puts on
  PATH); also VS-bundled
  `Common7\IDE\CommonExtensions\Microsoft\CMake\{CMake\bin\cmake.exe, Ninja\ninja.exe}`.
- **Geo deps via conda**: `C:\ProgramData\anaconda3\envs\gdal` (python 3.12)
  ships MSVC import libs: `gdal.lib geos.lib geos_c.lib proj.lib spatialite.lib
  mod_spatialite.lib sqlite3.lib zstd.lib libzstd.lib` (+libtiff, openssl,
  libarchive); conda-meta versions: **gdal 3.12.2, geos 3.14.1, proj 9.8.0,
  sqlite 3.52.0, zstd 1.5.7, zlib 1.3.1, libexpat 2.7.4**; and
  `osgeo.gdal 3.12.2` IS importable there (`python -c "from osgeo import gdal"`
  → 3.12.2). It lacks libzip/exiv2/gsl/protobuf/Qt6/qtkeychain/qca/qscintilla.
- **conda-forge win-64 availability verified via `conda search`** (read-only
  network query): `qt6-main 6.11.2`, `qt6-multimedia 6.11.2`, `qtkeychain
  0.17.0`, `qca 2.3.12`, `qscintilla2 2.14.1`, `exiv2 0.28.9`, `gsl 2.8`,
  `libzip 1.11.2`, `libprotobuf 7.36.1`, `winflexbison 2.5.25`,
  `postgresql 18.6` — all present for win-64.
- **PySide6 6.11.2** in BOTH `<wt>/.venv` and main-checkout `.venv` (cp312);
  the wheel's bundled `Qt6Core.dll` is **6.11.2.0** — an exact version match
  to conda `qt6-main=6.11.2`, which is what ADR 0059's private-ABI note wants.
- RAM 32 GB; C: ~1.2 TB free.

Missing / caveats:

- **Qt6 dev headers: none.** `qmake` found is Anaconda base Qt **5.15.2**
  (`C:\ProgramData\anaconda3\Library\bin\qmake`, `include/qt` = Qt5 layout).
  PySide6 wheels' `PySide6/include/QtCore` contains only 3 PySide-specific
  headers (`pyside6_qtcore_python.h qiopipe.h qtcorehelper.h`) — NOT a Qt
  dev header set; full headers must come from conda `qt6-main` (or
  vcpkg/OSGeo4W, neither installed; aqtinstall documented broken in-repo).
- **No pkg-config** on PATH → setup.py's Qt-include fallback is unusable;
  `PALEO_QGIS_CMAKE_PREFIX` is the only route.
- `<wt>/.venv` (uv venv) has **no pip** and **no pybind11/ninja**; pytest
  9.1.1 present but **no pytest-qt / pytest-timeout** (CI installs both).
- Neither project venv can `import osgeo` (only the conda `gdal` env can).
- `<wt>` submodules `third_party/gdal` and `third_party/proj` are NOT
  initialized (`git submodule status` shows `-`) — irrelevant to the bridge
  (see §2.4) but blocks `build_vendored_gdal.sh` usage anyway.
- No vcpkg, no OSGeo4W, no chocolatey/scoop.

## 4. Recommended path — fresh Windows vendor build against a conda-forge prefix

Port the CI's proven conda trick to Windows (conda-forge win-64 packages are
MSVC-built and binary-compatible with the local VS2022 toolset):

Step 0 — venv build deps (uv venv has no pip):

```powershell
cd C:\Users\wangj.KEVIN\projects\paleo-workbench\.worktrees\qgis-geolayer-cartography-v7
uv pip install "pybind11>=2.12" "ninja>=1.11" pytest-qt pytest-timeout
```

Step 1 — one dependency prefix (single env; ~3-5 GB). Qt pinned to 6.11.2 to
match PySide6 6.11.2's bundled Qt exactly (ADR 0059 private-ABI rule):

```powershell
conda create -y -p C:\Users\wangj.KEVIN\paleo-qgis-deps -c conda-forge ^
  qt6-main=6.11.2 qt6-multimedia=6.11.2 qtkeychain qca qscintilla2 ^
  exiv2 gsl libzip libprotobuf protobuf winflexbison postgresql ^
  gdal geos proj sqlite spatialite zstd libexpat zlib
```

(`gdal geos proj sqlite spatialite zstd` could instead be reused from the
existing `C:\ProgramData\anaconda3\envs\gdal` via a second `CMAKE_PREFIX_PATH`
entry, but one env avoids DLL mixing at runtime — prefer the single env.)

Step 2 — MSVC + tools environment (any shell):

```powershell
cmd /c "`"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat`" && set" | # import into session (pattern from scripts/build_and_test_windows.ps1:21-38)
$env:PATH = "$env:APPDATA\Python\Python313\Scripts;$env:PATH"   # cmake 4.4.2 + ninja 1.13
```

Step 3 — vendor build + bridge (fresh; -j2 per build-budget policy). Build the
vendor tree ONCE into a neutral path so every worktree can later
`PALEO_QGIS_REUSE_VENDOR=1` it (setup.py:75-85 is designed for this):

```powershell
$env:PALEO_WITH_QGIS_RENDERER = "1"
$env:PALEO_QGIS_BUILD_JOBS     = "2"
$env:PALEO_QGIS_BUILD_DIR      = "C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor"
$env:PALEO_QGIS_CMAKE_PREFIX   = "C:\Users\wangj.KEVIN\paleo-qgis-deps\Library"
$env:CMAKE_PREFIX_PATH         = "C:\Users\wangj.KEVIN\paleo-qgis-deps\Library"
$env:LIB = "C:\Users\wangj.KEVIN\paleo-qgis-deps\Library\lib;$env:LIB"   # Qt6Svg.lib/Qt6PrintSupport.lib for the ext link
uv pip install -e native/qgis_render_bridge
```

Step 4 — runtime (Windows analogue of CI's LD_LIBRARY_PATH unification): put
the vendor DLL dir and the conda prefix's bin FIRST on PATH so one Qt 6.11.2
set (the one the vendor build linked) serves bridge + PySide6:

```powershell
$env:PATH = "C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor\output\bin;C:\Users\wangj.KEVIN\paleo-qgis-deps\Library\bin;$env:PATH"
$env:QT_QPA_PLATFORM = "offscreen"
python -c "import qgis_render_bridge; print(qgis_render_bridge.__file__)"
python -m pytest -q -m qgis tests/    # PALEO_REQUIRE_QGIS=1 to fail-closed
```

### Estimates (from in-repo evidence, scaled to -j2)

| Item | Evidence | Estimate here |
|---|---|---|
| conda env create + solve | package sizes ~1-3 GB | 10-25 min |
| vendored QGIS core+gui+analysis, Release, Ninja | CI: "~50 min" at -j4 (4 vCPU); workflow header "~20-60 min"; README.md:95: "首次构建 vendored QGIS 需数小时" | **1.5-4 h at -j2** (MSVC typically slower than gcc per TU) |
| bridge extension (7 TUs) | v5: "~3 min" per rebuild at -j2 (Linux) | 5-15 min |
| disk | v5 vendor tree = 1.1 GB (Linux) | vendor ~1.5-2.5 GB + conda ~3-5 GB; trivial vs 1.2 TB free |
| memory | -j2 × MSVC QGIS TU peak (~1-2.5 GB each) | ≤ ~5 GB peak — safe on 32 GB |

Engineering time beyond machine time: the reduced-flag combo has never been
configured on Windows in-repo; budget **0.5-1 day** for first-configure fixes
(see B3).

## 5. Blockers and risks (explicit)

- **B1 — Qt6 dev headers absent (biggest prerequisite).** Not on the machine
  today (Anaconda=Qt5; PySide6 wheels carry no usable C++ headers; no
  pkg-config fallback). Resolution: conda `qt6-main=6.11.2` win-64 —
  availability VERIFIED via conda search; it also supplies Core5Compat,
  Sql private headers, Qml/Quick/UiTools (CI-proven set on Linux; same
  packaging on win-64). aqtinstall is documented broken (qgis-renderer.yml
  header); vcpkg would need bootstrap + multi-hour Qt build — rejected.
- **B2 — Qt Multimedia split.** `qt6-main` alone lacks Multimedia (CI note
  #1147); `qt6-multimedia=6.11.2` must be in the env (done in Step 1).
- **B3 — first Windows configure of the vendored QGIS is untested in-repo.**
  Expect to hand-hold: QCA/QScintilla/Qt6Keychain find-modules vs conda's
  layout (FindQScintilla wants libs named `qscintilla2-qt6`/`qt6scintilla2`;
  Qt6Keychain is CONFIG mode), winflexbison exe names (`win_flex`), protoc on
  PATH, `LIB_DIR` env convention (`$ENV{LIB_DIR}/lib` appears in several find
  modules — set `LIB_DIR=C:\Users\wangj.KEVIN\paleo-qgis-deps\Library` if
  needed). CMake fails loudly per design; each fix is a re-run of Step 3.
- **B4 — setup.py Windows specifics.** (i) It assumes `<prefix>/include/qt6`
  with module subdirs — matches conda-forge layout (verify on first run; if
  conda puts headers elsewhere, PALEO_QGIS_CMAKE_PREFIX must point at the
  dir whose child is `include\qt6`). (ii) `libraries=["Qt6Svg",
  "Qt6PrintSupport"]` passes no `library_dirs` — MSVC link.exe needs those
  `.lib`s on `LIB` (hence the `LIB` export in Step 3). (iii) It expects
  `output/lib/qgis_core.lib` on win32 — consistent with the bridge
  CMakeLists WIN32 expectations; verify crssync/resources target produces
  `resources/srs.db` on MSVC (PROJ+sqlite are in the prefix).
- **B5 — venv gaps (trivial).** No pip/pybind11/ninja/pytest-qt/pytest-timeout
  in the uv venv — Step 0 installs them; the PEP 517 isolated build also
  fetches pybind11 itself (pyproject.toml).
- **B6 — runtime DLL unification (Windows LD_LIBRARY_PATH analogue).** The
  .pyd pulls in qgis_*.dll + ~30 Qt6/geo DLLs; PATH order (Step 4) must put
  the conda prefix before anything else shipping Qt (PySide6's own dir).
  Because PySide6 6.11.2 bundles exactly Qt 6.11.2, a same-name DLL already
  loaded by PySide6 will satisfy the loader — the deliberate single-set
  ordering mirrors the CI's fix for the Core5Compat/private-ABI mixing
  incidents documented in the workflow header.
- **B7 — not blockers:** vendored GDAL (ADR 0060 keeps the QGIS build on a
  normal GDAL dev package — conda `gdal` provides it, MSVC .lib);
  `third_party/gdal|proj` submodules (uninitialized, unneeded); srs.db is
  generated by the `resources` target during the build.
- **B8 — -j2 policy** (v5 D8 / `PALEO_QGIS_BUILD_JOBS` default 2) applies;
  it stretches the vendor build to the 1.5-4 h band.

## 6. Alternatives considered and rejected

- **Reuse an existing build** — ruled out: no `build/qgis-vendor`, no
  `srs.db` anywhere under `C:\Users\wangj.KEVIN\projects` (given), and this
  audit additionally found none in either WSL distro (§2.6).
- **WSL/archlinux build (CI recipe verbatim)** — feasible (archlinux is
  Running) and lowest-uncertainty, but produces a Linux `.so` that the
  Windows cp312 venv can never import; only valid if the whole develop/test
  loop moves to WSL, which contradicts the goal of importing in `<wt>/.venv`.
  Keep as fallback for quick test verification while the Windows build lands.
- **vcpkg / OSGeo4W / aqtinstall** — none installed; vcpkg Qt build is
  hours-to-days; aqtinstall documented broken upstream in-repo; OSGeo4W is a
  second package manager with no in-repo precedent. The conda-forge route
  reuses the CI's exact, documented dependency strategy.
