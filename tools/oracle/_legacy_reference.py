"""sys.path shim to the archived Python reference implementation.

The retired Python product implementation lives under
``legacy/python_reference/product`` (see ``docs/development/python-retirement/``).
Oracle/fixture generators still use it as the semantic reference for parity
fixture generation — this module is the single sanctioned bridge: it puts the
archive's ``product`` root on ``sys.path`` so ``import paleo_workbench``
resolves against the archived reference.

Development tooling only. The archived tree must never be imported by the
production C++ application, packaged into the native product, installed as
runtime resources, or used as a runtime fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ARCHIVED_PRODUCT_ROOT = (
    Path(__file__).resolve().parents[2] / "legacy" / "python_reference" / "product"
)


def ensure_legacy_reference() -> Path:
    """Put the archived product root on sys.path (idempotent); return it."""
    root = _ARCHIVED_PRODUCT_ROOT
    if not root.is_dir():
        raise RuntimeError(
            f"archived Python reference not found at {root} — the retirement "
            "layout expects legacy/python_reference/product (see "
            "docs/development/python-retirement/)"
        )
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root
