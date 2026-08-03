"""Entry point: ``python -m well_log_workstation`` (#216).

Must configure Qt platform **before** QApplication is created.
"""

from __future__ import annotations

import sys

from well_log_workstation.qt_platform import configure_qt_platform_for_session


def main(argv: list[str] | None = None) -> int:
    _ = argv  # reserved for future CLI flags
    configure_qt_platform_for_session(warn=True)

    from PySide6.QtWidgets import QApplication

    from well_log_workstation.shell import WellLogWorkstationWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Well Log Workstation")
    app.setOrganizationName("paleo-workbench")

    window = WellLogWorkstationWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
