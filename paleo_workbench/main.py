from __future__ import annotations

import sys

# Prefer Wayland on Wayland sessions; clear accidental QT_QPA_PLATFORM=xcb
# before any QGuiApplication is constructed.
from paleo_workbench.qt_platform import configure_qt_platform_for_session

configure_qt_platform_for_session()

# Bootstrap geoviz paths before other workbench imports (ISS-ENV-01).
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

if not ensure_geoviz_on_path():
    print(
        "ERROR: cannot import geoviz. From the repo root run:\n"
        "  python -m pip install -e .\n"
        "  python -m pip install -r requirements-geoviz.txt\n"
        "Or set PYTHONPATH to include geo-viz-engine and its packages.",
        file=sys.stderr,
    )
    raise SystemExit(2)

from PySide6.QtWidgets import QApplication

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.ui import tokens


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(tokens.QSS_TEMPLATE)

    from paleo_workbench.viz.render_accel import install_geoviz_acceleration

    install_geoviz_acceleration()
    try:
        # Deferred: keep CLI startup light (pulls in pipeline + project stack).
        from paleo_workbench.pipeline.bootstrap import (
            bootstrap_sample_project,
            resolve_sample_data_root,
        )

        data_root = resolve_sample_data_root()
        project = bootstrap_sample_project(data_root).document
    except Exception:
        project = None

    window = PaleoWorkbenchWindow(project=project)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
