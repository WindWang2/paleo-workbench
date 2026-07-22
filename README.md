# Paleo Workbench

Paleogeographic map compilation desktop workbench (PySide6) with the
`geo-viz-engine` visualization submodule.

## Setup

```bash
# From the repository root
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

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
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
