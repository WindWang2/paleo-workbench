from __future__ import annotations

import os
from pathlib import Path

from paleo_workbench.project.models import ResourceItem

# Types cycle for filter stress
_TYPES = (
    ("well_log", "las"),
    ("seismic", "sgy"),
    ("horizon", "dat"),
    ("document", "pdf"),
)


def stress_n(default: int = 2000) -> int:
    raw = os.environ.get("DATAPAGE_STRESS_N")
    if raw:
        return max(1, int(raw))
    return default


def make_mock_resources(n: int) -> list[ResourceItem]:
    items: list[ResourceItem] = []
    for i in range(n):
        rtype, fmt = _TYPES[i % len(_TYPES)]
        name = f"asset_{i:05d}.{fmt}"
        items.append(
            ResourceItem(
                name=name,
                path=f"/mock/data/{name}",
                type=rtype,
                format=fmt,
                status="indexed",
                checksum=None,
            )
        )
    return items


def make_tmp_tree(base: Path, n: int = 300) -> Path:
    """Create n tiny files under base/stress_import/ for import_folder timing."""
    root = base / "stress_import"
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        # Mix extensions for classifier variety; keep tiny
        ext = "las" if i % 3 == 0 else ("txt" if i % 3 == 1 else "dat")
        p = root / f"f_{i:04d}.{ext}"
        p.write_bytes(b"x")
    return root
