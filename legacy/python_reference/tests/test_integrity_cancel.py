"""#655: integrity SHA-256 must stop cooperatively when cancel is requested."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.integrity_worker import IntegrityWorker, compute_sha256


def test_compute_sha256_returns_none_when_cancelled(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"x" * (65536 * 8))
    seen = {"n": 0}

    def is_cancelled() -> bool:
        seen["n"] += 1
        return seen["n"] > 2

    assert compute_sha256(path, is_cancelled=is_cancelled) is None
    assert seen["n"] > 2


def test_integrity_worker_stops_before_finishing_list(tmp_path: Path) -> None:
    assets = []
    for index in range(6):
        path = tmp_path / f"asset-{index}.bin"
        path.write_bytes(b"payload" * 1000)
        assets.append(
            ResourceItem(
                name=path.name,
                path=str(path),
                type="document",
                format="bin",
                checksum="deadbeef",
            )
        )

    worker = IntegrityWorker(assets, project_root=tmp_path)
    reports = []
    worker.finished.connect(reports.append)
    worker.progress.connect(lambda *_args: worker.cancel())
    worker.run()

    assert reports
    report = reports[0]
    finished = len(report.results)
    assert finished < len(assets)
