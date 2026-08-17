# Paleo Workbench

Paleogeographic map compilation desktop workbench (PySide6) with visualization
and well-log engine **submodules**:

| Submodule | Role | Public repo |
|-----------|------|-------------|
| `geo-viz-engine` | Map / geologic visualization packages | [WindWang2/geo-viz-engine](https://github.com/WindWang2/geo-viz-engine) |
| `well-log-engine` | C++20 well-log SDK + **WellPlot Desktop** host app | [WindWang2/well-log-engine](https://github.com/WindWang2/well-log-engine) |

**WellPlot Desktop** (log-first desktop; example and/or product as it matures) is no longer packaged in this repo’s Python tree. It lives at:

`well-log-engine/apps/wellplot-desktop/` — run with `pip install -e well-log-engine/apps/wellplot-desktop && wellplot-desktop`

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

**Windows source checkout:** currently blocked by the `geo-viz-engine`
submodule, which ships filenames Windows filesystems cannot materialize
(`{"filename": "ui-ref-*.png"}` — tracking issue #441). The fix lives in the
geo-viz-engine repo (rename + release) followed by a gitlink bump here; the
CI guard step fails on any *new* Windows-invalid submodule path. Until the
bump lands, Windows developers can init only the `well-log-engine` submodule
(`git submodule update --init well-log-engine`), but geoviz and therefore the
app will be unavailable.

When packages are not installed, `paleo_workbench.env_bootstrap` prepends the
checkout's `geo-viz-engine` package roots on import of `paleo_workbench` and
again at the app entry points.

```bash
# Entry points (after `pip install .` / `pip install -e .`, or from a source
# checkout with the geoviz bootstrap)
paleo-workbench            # console script
python -m paleo_workbench  # module entry
python -m paleo_workbench.main
```

If geoviz cannot be imported the app exits with code 2 and prints the install
commands (geoviz is intentionally not a hard dependency; see
`requirements-geoviz.txt`). `python paleo_workbench/main.py` script mode is
also supported (it re-adds the repo root to `sys.path`).

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

## QGIS renderer (opt-in)

`paleo_workbench.mapping.map_render_backend` prefers the QGIS production
renderer when `prefer_qgis=True`, but that backend requires the optional
`qgis_render_bridge` extension (a vendored-QGIS build under
`native/qgis_render_bridge`; QGIS sources are fixed in `third_party/qgis`).
It is **not** part of the default install and the main CI gate does **not**
cover it — the CI `Tests` matrix installs neither QGIS nor the bridge, so the
fallback renderer is the effectively-gated path and every QGIS test
self-skips there (they carry the `qgis` pytest marker; skip reasons show the
exact enablement commands).

Build it explicitly (needs Qt6 dev headers, cmake and ninja on the system):

```bash
python -m pip install -e ".[qgis-renderer]"
PALEO_WITH_QGIS_RENDERER=1 python -m pip install -e native/qgis_render_bridge
python -m pytest -q -m qgis tests/   # run the QGIS renderer tests
```

A dedicated CI leg (`.github/workflows/qgis-renderer.yml`) builds the bridge
and runs an import smoke plus the vendor-integrity checks. It is fail-closed
but only runs on manual dispatch or on changes touching
`native/qgis_render_bridge/**` / `third_party/qgis/**` — normal PRs skip it.
See `docs/ci-merge-policy.md` for the coverage statement.

## 3D Geological Modeling (`viz/geomodel`)

Page 11 adds a full 3D geological modeling workbench with:

- **Borehole / Tunnel / Fault** 3D rendering (OpenGL cylinders, swept tubes, fault surfaces)
- **GPU 3-way interactive clipping** (X / Y / Z axis real-time cut)
- **Well-seismic tie calibration** — Ricker synthetic seismograms, cross-correlation auto-tie, 3D GR log curve overlay
- **Seismic amplitude slice** overlay in the 3D viewport
- **Rule-based consistency advisor** — borehole layer overlap detection, coplanar fault warning
- **Numerical simulation export** — FLAC3D (`.f3grid`) and Abaqus (`.inp`) structured hex grids

See [`docs/geomodel-architecture.md`](docs/geomodel-architecture.md) for the full module architecture.

## Interpolation note (ISS-KRIG-01 resolved)

The preparation combobox option **克里金** runs REAL variogram ordinary
kriging: empirical-variogram fitting plus an ordinary-kriging solve, with the
kriging variance grid exposed alongside the prediction (geo-viz-engine
`geoviz_plots.factor.kriging`). The earlier MVP linear placeholder is gone.
**IDW** (with optional fault barriers) and **方向趋势** remain available.

## Well Log Workstation

Standalone log-first app (not the paleogeography workbench), living in the
`well-log-engine` submodule. See
[`well-log-engine/apps/wellplot-desktop/well_log_workstation/README.md`](well-log-engine/apps/wellplot-desktop/well_log_workstation/README.md).

```bash
# From the repository root: install the app, then run it
pip install -e well-log-engine/apps/wellplot-desktop
unset QT_QPA_PLATFORM   # Wayland session default
wellplot-desktop        # or: python -m well_log_workstation (from the app dir)
```
