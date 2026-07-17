from __future__ import annotations

import sys

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
    window = PaleoWorkbenchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
