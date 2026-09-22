"""``python -m paleo_workbench`` package entry point (packaging #440).

Forwards to ``paleo_workbench.main.main()`` so an installed wheel has a
runnable module entry in addition to the ``paleo-workbench`` console script.
"""

from __future__ import annotations

import sys

from paleo_workbench.main import main

if __name__ == "__main__":
    sys.exit(main())
