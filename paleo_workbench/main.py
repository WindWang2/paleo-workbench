from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.ui import tokens


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(tokens.QSS_TEMPLATE)
    window = PaleoWorkbenchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
