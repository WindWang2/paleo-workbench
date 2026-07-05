from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from paleo_workbench.app import PaleoWorkbenchWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = PaleoWorkbenchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())