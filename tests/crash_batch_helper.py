"""SIGKILL crash-during-bulk-registration helper (spawned by
tests/test_crash_scale.py).

Registers *batch* resources inside ONE ``batch_save`` (the D4 chunking is
deliberately overridden to a single chunk) and SIGKILLs the process at the
same armed points as ``crash_kill_helper``:

- ``replace`` — killed mid-transaction: WAL recovery must roll the whole
  registration back (0 assets survive).
- ``bak`` — killed immediately after the transaction committed: all rows
  survive.

Either way the reopened catalog must be consistent and complete.
"""

import os
import signal
import sys
from pathlib import Path

from crash_kill_helper import _KillingConn, _kill_self  # noqa: I001


def main() -> None:
    mode = sys.argv[1]  # "replace" | "bak"
    project = Path(sys.argv[2])
    batch = int(sys.argv[3]) if len(sys.argv) > 3 else 2_000
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")

    from paleo_workbench.catalog import db as db_mod
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.project.models import ResourceItem
    from paleo_workbench.catalog.lifecycle import register_resource_input
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.runtime import set_catalog

    svc = DataCatalogService.open(project)
    set_catalog(CoreCatalogAdapter(svc))

    incoming = project.parent / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    resources = []
    for i in range(batch):
        src = incoming / f"f_{i:06d}.las"
        src.write_bytes(b"payload" * 4)
        resources.append(
            ResourceItem(name=src.name, path=str(src), type="well_log", format="las")
        )

    state = {"mode": None, "count": 0}
    real_connect = db_mod.CatalogIndex._connect

    def _armed_connect(self):
        conn = real_connect(self)
        if state["mode"] is None:
            return conn
        return _KillingConn(conn, state)

    db_mod.CatalogIndex._connect = _armed_connect  # type: ignore[assignment]
    real_apply = db_mod.CatalogIndex.apply_changes

    def _armed_apply(self, document, dirty, **kwargs):
        if state["mode"] == "bak":
            real_apply(self, document, dirty, **kwargs)
            _kill_self()  # committed, then died before anything else
        real_apply(self, document, dirty, **kwargs)

    db_mod.CatalogIndex.apply_changes = _armed_apply  # type: ignore[assignment]

    state["mode"] = mode
    with svc.batch_save():
        for resource in resources:
            register_resource_input(resource)
    # Never reached: killed inside/after the flush.


if __name__ == "__main__":
    main()
