"""SIGKILL crash-during-persist helper (spawned by the crash-safety tests).

Runs a real DataCatalogService against a tmp project, imports one asset
(flush #1), then imports a second asset while SIGKILLing itself at a chosen
point inside the second canonical SQLite flush (#1027):

- ``replace`` (mid-transaction) — killed after a few statements INSIDE the
  apply_changes transaction: the WAL holds uncommitted frames that recovery
  must roll back, leaving exactly the first import.
- ``bak`` (post-commit) — killed immediately AFTER the transaction
  committed: both imports must survive.

Either way the reopened project must be consistent and writable.
"""

import os
import signal
import sys
from pathlib import Path


class _KillingConn:
    """Proxy over the sqlite3 connection that kills the process mid-tx."""

    def __init__(self, conn, state):
        self._conn = conn
        self._state = state

    def _tick(self) -> None:
        self._state["count"] += 1
        if self._state["mode"] == "replace" and self._state["count"] >= 4:
            _kill_self()

    def execute(self, sql, *args):
        self._tick()
        return self._conn.execute(sql, *args)

    def executemany(self, sql, rows):
        self._tick()
        return self._conn.executemany(sql, rows)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _kill_self() -> None:
    if hasattr(signal, "SIGKILL"):
        os.kill(os.getpid(), signal.SIGKILL)
    else:
        # On Windows, signal.SIGTERM triggers Win32 TerminateProcess
        os.kill(os.getpid(), signal.SIGTERM)


def main() -> None:
    mode = sys.argv[1]  # "replace" | "bak" (historical param names)
    project = Path(sys.argv[2])
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")

    from paleo_workbench.catalog import db as db_mod
    from paleo_workbench.catalog.service import DataCatalogService

    svc = DataCatalogService.open(project)
    incoming = project.parent / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "x.bin").write_bytes(b"first-payload" * 1000)
    svc.import_raw(incoming / "x.bin")  # flush #1 (committed)

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
    (incoming / "y.bin").write_bytes(b"second-payload" * 700)
    svc.import_raw(incoming / "y.bin")  # killed mid-flush; never returns


if __name__ == "__main__":
    main()
