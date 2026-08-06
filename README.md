# Paleo Workbench

Paleogeographic map compilation desktop workbench (PySide6) with visualization
and well-log engine **submodules**:

| Submodule | Role | Public repo |
|-----------|------|-------------|
| `geo-viz-engine` | Map / geologic visualization packages | [WindWang2/geo-viz-engine](https://github.com/WindWang2/geo-viz-engine) |
| `well-log-engine` | C++20 well-log rendering SDK (OpenGL + Qt/Python adapters) | [WindWang2/well-log-engine](https://github.com/WindWang2/well-log-engine) |

## Setup

```bash
# From the repository root
git submodule update --init --recursive
python -m pip install -e .
python -m pip install -r requirements-geoviz.txt   # editable geoviz_* packages
python -m pip install -e ".[dev]"                  # pytest / pytest-qt
```

Editable installs are the **preferred** way to make `import geoviz` work for any
Python process (ISS-ENV-01). Pytest also configures package roots via
`pyproject.toml` `[tool.pytest.ini_options].pythonpath`.

When packages are not installed, `paleo_workbench.env_bootstrap` prepends the
checkout's `geo-viz-engine` package roots on import of `paleo_workbench` and
again at the `python -m paleo_workbench.main` entry point.

```bash
# Entry point (after install or from a source checkout with bootstrap)
python -m paleo_workbench.main
```

### Qt display platform (Linux)

| Context | `QT_QPA_PLATFORM` |
|---------|-------------------|
| **Desktop app** (normal use) | **Unset** — on Wayland sessions Qt uses **wayland** (default today). |
| **CI / headless pytest** | `offscreen` (not X11). |
| **XWayland debug only** | `xcb` plus `PALEO_FORCE_XCB=1` if the session is Wayland. |

Do **not** set `QT_QPA_PLATFORM=xcb` as a general default. `DISPLAY=:N` under a Wayland session usually means XWayland compatibility, not “the app should run as X11”. The app entry point clears accidental `xcb` on Wayland unless `PALEO_FORCE_XCB=1`.

## Tests

```bash
# CI / headless (recommended default for automated runs)
QT_QPA_PLATFORM=offscreen python -m pytest -q

# Local GUI-session tests: leave QT_QPA_PLATFORM unset (Wayland on Wayland sessions)
python -m pytest -q
```

## 3D Geological Modeling (`viz/geomodel`)

Page 11 adds a full 3D geological modeling workbench with:

- **Borehole / Tunnel / Fault** 3D rendering (OpenGL cylinders, swept tubes, fault surfaces)
- **GPU 3-way interactive clipping** (X / Y / Z axis real-time cut)
- **Well-seismic tie calibration** — Ricker synthetic seismograms, cross-correlation auto-tie, 3D GR log curve overlay
- **Seismic amplitude slice** overlay in the 3D viewport
- **AI consistency advisor** — borehole layer overlap detection, coplanar fault warning
- **Numerical simulation export** — FLAC3D (`.f3grid`) and Abaqus (`.inp`) structured hex grids

See [`docs/geomodel-architecture.md`](docs/geomodel-architecture.md) for the full module architecture.

## Interpolation note (ISS-KRIG-01)

The preparation combobox option **克里金(MVP·线性)** is an explicit MVP stand-in:
it maps to SciPy **linear** triangulation, not full variogram kriging. Prefer
**IDW** (with optional fault barriers) or **方向趋势** for production-style
workflows until a true kriging backend is added.

## Well Log Workstation

Standalone log-first app (not the paleogeography workbench). See
[`well_log_workstation/README.md`](well_log_workstation/README.md).

```bash
unset QT_QPA_PLATFORM   # Wayland session default
python -m well_log_workstation
```
