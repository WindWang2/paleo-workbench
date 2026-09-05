from __future__ import annotations

import logging
import sys
from pathlib import Path

# `python paleo_workbench/main.py` script mode puts the *package directory* on
# sys.path[0], which breaks `import paleo_workbench`; re-add the repo root so
# script mode resolves like the packaged entry points (packaging #440).
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# PySide6 imports at module level are side-effect free; the Qt global-state
# mutations (platform policy, default surface format, geoviz gate) live in
# main() so a bare `import paleo_workbench.main` cannot change Qt state
# (packaging #440).
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from paleo_workbench.qt_platform import configure_qt_platform_for_session


def _apply_qt_desktop_policy() -> None:
    """Prefer Wayland on Wayland sessions; clear accidental QT_QPA_PLATFORM=xcb
    before any QGuiApplication is constructed. Force desktop OpenGL before
    QApplication is created: without this, PySide6's Qt on Wayland + NVIDIA
    selects a GLES 2.0 EGL config, and any embedded QOpenGLWidget (e.g.
    WellLogView) gets a black screen because its desktop GL context cannot
    share with the GLES main context.
    """
    configure_qt_platform_for_session()
    _apply_wayland_fractional_scale_guard()

    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)


def _apply_wayland_fractional_scale_guard() -> None:
    """Optional integer-scale guard for Wayland fractional-scale sessions.

    Under Wayland fractional scaling (e.g. Plasma 125%) Qt 6 renders crisp
    device-pixel-ratio buffers, but the final compositor path can deliver the
    window bitmap-upsampled: thin canvas annotations (seismic ms ticks, map
    axis numbers) visibly rasterize while regular UI text stays sharp.
    Integer scales (xcb/DPR 2.0) are unaffected. Setting
    ``PALEO_WAYLAND_INTEGER_SCALE=1`` rounds the device scale to an integer
    (crisp canvas text; UI elements become physically larger/smaller by the
    rounding step). Default: keep the fractional scale (current look) — the
    size trade-off is a user decision.
    """
    import os

    if os.environ.get("PALEO_WAYLAND_INTEGER_SCALE", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    platform = os.environ.get("QT_QPA_PLATFORM", "").lower()
    if session_type != "wayland" and platform not in {"wayland", ""}:
        return
    from PySide6.QtCore import Qt

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.Round
    )
    logging.getLogger("paleo_workbench").info(
        "PALEO_WAYLAND_INTEGER_SCALE=1: device scale rounded to an integer "
        "to keep canvas annotations vector-crisp under fractional scaling"
    )


def _parse_cli_args(argv: list[str]) -> int | None:
    """Handle non-GUI command-line arguments prior to Qt application initialization.

    Returns exit code integer if the application should terminate immediately,
    or None to proceed to GUI startup.
    """
    if "--help" in argv or "-h" in argv:
        from paleo_workbench.env_bootstrap import geoviz_bootstrap_status

        status = geoviz_bootstrap_status()
        print(
            "usage: paleo-workbench [OPTIONS]\n\n"
            "Paleogeographic map compilation desktop workstation.\n\n"
            "Options:\n"
            "  -h, --help       Show this help message and exit.\n"
            "  --version        Show application version and environment status.\n"
            "  --diagnostics    Show detailed system, geoviz, and native backend diagnostics.\n"
            "\nEnvironment Status:\n"
            f"  Repository Root: {status['repo_root'] or 'Not detected (running from installed package)'}\n"
            f"  GeoViz Core:     {'Available' if status['importable'] else 'Unavailable'}\n"
            f"  Install Command: {status['preferred_install']}"
        )
        return 0

    if "--version" in argv:
        import paleo_workbench

        version = getattr(paleo_workbench, "__version__", "0.2.17a0")
        print(f"paleo-workbench {version} (CPython {sys.version.split()[0]})")
        return 0

    if "--diagnostics" in argv or "--check-env" in argv:
        from paleo_workbench.env_bootstrap import (
            ensure_geoviz_on_path,
            geoviz_bootstrap_status,
        )

        ensure_geoviz_on_path()
        status = geoviz_bootstrap_status()
        print("=== Paleo Workbench Environment Diagnostics ===")
        print(f"Python:          {sys.executable}")
        print(f"Repo Root:       {status['repo_root']}")
        print(f"GeoViz Core:     {'OK' if status['importable'] else 'MISSING'}")
        print("Subpackages:")
        subpkgs = status.get("subpackages", {})
        for name, ok in subpkgs.items():
            print(f"  - {name:25s}: {'OK' if ok else 'NOT INSTALLED'}")
        return 0

    return None


def _require_geoviz() -> None:
    """Bootstrap geoviz paths and give an actionable error when unavailable.

    Keeps the SystemExit(2) contract of the previous module-level gate, but
    only when an entry point actually starts the app (ISS-ENV-01).
    """
    from paleo_workbench.env_bootstrap import (
        ensure_geoviz_on_path,
        geoviz_bootstrap_status,
        load_local_env,
    )

    load_local_env()

    if not ensure_geoviz_on_path():
        print(
            "ERROR: cannot import geoviz. From the repo root run:\n"
            "  python -m pip install -e .\n"
            "  python -m pip install -r requirements-geoviz.txt\n"
            "Or set PYTHONPATH to include geo-viz-engine and its packages.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    status = geoviz_bootstrap_status()
    missing = status.get("missing_subpackages", [])
    if missing:
        logging.getLogger("paleo_workbench").warning(
            "Some optional geo-viz-engine subpackages are not installed: %s. "
            "Specific pages (e.g. 3D seismic/well-tie) may be unavailable. "
            "To install, run: python -m pip install -r requirements-geoviz.txt",
            ", ".join(missing),
        )


def main() -> int:
    exit_code = _parse_cli_args(sys.argv[1:])
    if exit_code is not None:
        return exit_code

    _apply_qt_desktop_policy()
    _require_geoviz()

    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.ui import tokens

    # P2-A: one call wires the global resource governance — active budget
    # pushed into the engine caches, pressure monitor bound, governor
    # admission installed on the global TaskScheduler. Idempotent and cheap;
    # failures degrade to ungoverned (previous behaviour), never block boot.
    try:
        from paleo_workbench.runtime import ensure_global_governance

        ensure_global_governance()
    except Exception:  # noqa: BLE001 — governance must never block startup
        logging.getLogger("paleo_workbench").warning(
            "resource governance unavailable; running ungoverned", exc_info=True
        )

    app = QApplication(sys.argv)
    # Theme the whole application through the manager (#1047): a frozen
    # light template here would fight every later theme switch on any
    # top-level window outside AppShell.
    from paleo_workbench.ui.theme import theme_manager

    theme_manager.load_persisted()
    app.setStyleSheet(theme_manager.get_qss())
    # 图标染色缓存随主题清空（B1）；幂等。
    from paleo_workbench.ui.workstation.common import install_theme_hook

    install_theme_hook()

    from paleo_workbench.viz.render_accel import install_geoviz_acceleration

    install_geoviz_acceleration()
    # P1-C: push the machine-derived VRAM cap into the engine's texture
    # ledger at boot so every 3D view shares ONE bounded budget instead of
    # running on the engine default (#1078 contract: 1 GiB at ≥16 GB RAM,
    # 512 MiB below). A missing engine ledger logs and continues.
    from paleo_workbench.runtime.resource_budget import active_budget, apply_vram_budget

    if not apply_vram_budget(active_budget()):
        logging.getLogger(__name__).debug(
            "VRAM budget not applied (engine ledger unavailable)"
        )
    window = PaleoWorkbenchWindow(project=None)
    window.show()
    # #941-7: the render backends' explicit teardown had no production caller
    # (canvas closeEvent never fires on quit). Flush threaded fallback workers
    # and cached layers on application quit instead of relying on interpreter
    # teardown — QGIS mirrors rely on it for a clean exit.
    app.aboutToQuit.connect(_shutdown_render_backends)
    return app.exec()


def _shutdown_render_backends() -> None:
    try:
        from paleo_workbench.mapping.map_render_backend import (
            shutdown_live_fallback_backends,
        )

        shutdown_live_fallback_backends()
    except Exception:  # noqa: BLE001 — teardown must never break quitting
        logging.getLogger("paleo_workbench").debug(
            "render backend shutdown failed", exc_info=True
        )


if __name__ == "__main__":
    raise SystemExit(main())
