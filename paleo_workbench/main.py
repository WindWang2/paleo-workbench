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
from PySide6.QtGui import QSurfaceFormat
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

    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)


def _require_geoviz() -> None:
    """Bootstrap geoviz paths and give an actionable error when unavailable.

    Keeps the SystemExit(2) contract of the previous module-level gate, but
    only when an entry point actually starts the app (ISS-ENV-01).
    """
    from paleo_workbench.env_bootstrap import ensure_geoviz_on_path, load_local_env

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


def main() -> int:
    _apply_qt_desktop_policy()
    _require_geoviz()

    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.ui import tokens

    app = QApplication(sys.argv)
    app.setStyleSheet(tokens.QSS_TEMPLATE)

    from paleo_workbench.viz.render_accel import install_geoviz_acceleration

    install_geoviz_acceleration()
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
