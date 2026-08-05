"""Entry point: ``python -m well_log_workstation`` (#216 / #290).

Must configure Qt platform **before** QApplication is created.
Product display name: WellPlot Desktop (package path unchanged).
"""

from __future__ import annotations

import sys

from well_log_workstation.branding import ORGANIZATION_NAME, PRODUCT_NAME
from well_log_workstation.qt_platform import configure_qt_platform_for_session


def main(argv: list[str] | None = None) -> int:
    _ = argv  # reserved for future CLI flags
    configure_qt_platform_for_session(warn=True)

    from PySide6.QtWidgets import QApplication

    from well_log_workstation.shell import WellLogWorkstationWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(PRODUCT_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)

    window = WellLogWorkstationWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
