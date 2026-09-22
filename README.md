# Paleo Workbench

Paleogeographic map compilation **desktop workbench**.

| Track | What it is | Entry |
| --- | --- | --- |
| **Native product (production shell)** | C++20 / Qt 6 / vendored QGIS — ribbon five-workspaces UI | `pwb-platform` (`apps/paleo_workbench_platform`) |
| **Legacy Python product** | PySide6 shell kept for parity / field workflows during conversion | `paleo-workbench` / `python -m paleo_workbench` |
| **Oracle / reference** | Python modules + `tools/oracle/*` that freeze fixtures for C++ kernels | not an install dependency of `pwb-platform` |

Submodules:

| Submodule | Role | Public repo |
|-----------|------|-------------|
| `geo-viz-engine` | Map / geologic visualization packages (Python reference; native ports live under `libs/`) | [WindWang2/geo-viz-engine](https://github.com/WindWang2/geo-viz-engine) |
| `well-log-engine` | C++20 well-log SDK + WellPlot Desktop / viewer stack | [WindWang2/well-log-engine](https://github.com/WindWang2/well-log-engine) |

**Documentation map**: start at [`docs/README.md`](docs/README.md).
**Module boundaries**: [`docs/architecture/module-map.md`](docs/architecture/module-map.md).
**C++ conversion snapshot**: [`docs/development/cpp-conversion-status.md`](docs/development/cpp-conversion-status.md).

---

## Native product (recommended)

### Requirements

- CMake ≥ 3.24, Ninja, C++20 toolchain (GCC/Clang on Linux; MSVC 2022 on Windows)
- Qt 6 (product presets target the project’s Qt 6.8+ workflow)
- Vendored QGIS SDK build under `native/qgis_render_bridge/build/qgis-vendor/output` (see existing platform docs / CI for how that tree is produced)

### Configure, build, smoke

```bash
git submodule update --init --recursive

cmake --preset linux-native-product          # or: windows-msvc-native-product
cmake --build build/native-product -j$(nproc)

# Headless product smoke (names vary slightly by build; both accepted by bootstrap)
build/native-product/apps/paleo_workbench_platform/pwb-platform --headless-self-check
build/native-product/apps/paleo_workbench_platform/pwb-platform --capabilities
```

Windows: use preset `windows-msvc-native-product` from a VS 2022 developer
environment (or `scripts/cpp-migration/Invoke-PlatformBuild.ps1` with the
resource gate). Heavy builds should go through
`scripts/cpp-migration/invoke-resource-gate.sh` /
`Invoke-ResourceGate.ps1` when multiple worktrees share a machine.

### Production UI

The adopted shell is the **ribbon five-workspaces** layout (data management →
智能预测 → 约束与单因素 → 综合编图 → 验证). Design authority:
[`docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/`](docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/).
Implementation: `libs/ui_ribbon` + app install seams (landed on `main` via
`fa9ba744`).

### Tests (native)

```bash
cd build/native-product
QT_QPA_PLATFORM=offscreen ctest --output-on-failure
# Focused families often used in conversion gates:
#   ctest -R '^platform\.' 
#   ctest -R 'mapping_kernel'
```

Integrated gate helper: `scripts/cpp-migration/run-integrated-gate.sh` (when
present on your checkout) and `scripts/cpp-migration/final-closure-gate.sh`.

---

## Legacy Python product

Still installable for conversion parity and workflows not yet retired
(M12). Prefer the native binary for new product work.

### Linux / macOS

```bash
git submodule update --init --recursive
python -m pip install -e .
python -m pip install -r requirements-geoviz.txt
python -m pip install -e ".[dev]"
paleo-workbench            # or: python -m paleo_workbench
```

### Windows (MSVC 2022)

```powershell
git submodule update --init --recursive
powershell -ExecutionPolicy Bypass -File .\scripts\build_and_test_windows.ps1
```

### Native C++ extensions used by the Python track (`[native]`)

Optional pybind accelerators (`grid_render_core`, `layer_model_core`,
`seismic_3d_core`, `well_log_core`, `map_edit_core`, …) remain relevant to the
**Python** product. The native `pwb-platform` closure does **not** load them
via Python; see
[`docs/development/geoviz-cpp-final-closure/04-python-retirement.md`](docs/development/geoviz-cpp-final-closure/04-python-retirement.md).

### Qt display platform (Linux)

| Context | `QT_QPA_PLATFORM` |
|---------|-------------------|
| **Desktop app** (normal use) | **Unset** — Wayland sessions use wayland |
| **CI / headless pytest / ctest GUI** | `offscreen` |
| **XWayland debug only** | `xcb` plus `PALEO_FORCE_XCB=1` |

### Python tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

---

## Architecture (short)

- **Host**: `apps/paleo_workbench_platform` (`pwb-platform`)
- **Libraries**: `libs/*` (63 libraries) — Qt-free domain cores + `ui_*` / `qgis`
- **Catalog**: single write rail (ADR 0056 family) via catalog / workflow
  closure adapters
- **Map stack**: vendored QGIS in the native product; Python track still uses
  `qgis_render_bridge` when built
- **Domain glossary**: [`CONTEXT.md`](CONTEXT.md)
- **ADRs**: [`docs/adr/`](docs/adr/)

## Agent notes

See [`CLAUDE.md`](CLAUDE.md) and [`docs/agents/`](docs/agents/). Follow the
Karpathy guidelines in `agent/skills/karpathy-guidelines/SKILL.md`.

## WellPlot Desktop

Standalone log-first app in `well-log-engine/apps/wellplot-desktop/` — not the
paleogeography workbench.

```bash
pip install -e well-log-engine/apps/wellplot-desktop
unset QT_QPA_PLATFORM
wellplot-desktop
```
