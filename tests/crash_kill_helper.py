"""SIGKILL crash-during-save helper (spawned by the crash-safety tests).

Runs a real DataCatalogService against a tmp project, imports one asset
(save #1), then imports a second asset while SIGKILLing itself at a chosen
point inside the second canonical save:

- ``replace``  — killed when the temp file is renamed over catalog.json
  (the canonical file has already been moved aside to catalog.json.bak).
- ``bak``      — killed while moving catalog.json → catalog.json.bak.
"""

import os
import signal
import sys
from pathlib import Path


def main() -> None:
    mode = sys.argv[1]
    project = Path(sys.argv[2])
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")

    from paleo_workbench.catalog.service import DataCatalogService

    svc = DataCatalogService.open(project)
    incoming = project.parent / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "x.bin").write_bytes(b"first-payload" * 1000)
    svc.import_raw(incoming / "x.bin")  # save #1

    import paleo_workbench.catalog.store as store_mod

    real_replace = store_mod.os.replace
    armed = {"on": False}

    def _killer(src, dst):
        dst_str = str(dst)
        if not armed["on"]:
            return real_replace(src, dst)
        if "catalog.json.bak" in dst_str and mode == "bak":
            os.kill(os.getpid(), signal.SIGKILL)
        if dst_str.endswith("catalog.json") and mode == "replace":
            os.kill(os.getpid(), signal.SIGKILL)
        return real_replace(src, dst)

    store_mod.os.replace = _killer  # type: ignore[assignment]
    armed["on"] = True
    (incoming / "y.bin").write_bytes(b"second-payload" * 700)
    svc.import_raw(incoming / "y.bin")  # killed mid-save; never returns


if __name__ == "__main__":
    main()
