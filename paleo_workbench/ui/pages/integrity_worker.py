"""Integrity Verification Worker: Non-blocking background checksum & file integrity verification.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, QThread, Signal, Slot

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_view_models import IntegrityState, asset_view_from_object


@dataclass
class IntegrityCheckReport:
    total_checked: int = 0
    verified_count: int = 0
    modified_count: int = 0
    missing_count: int = 0
    unmanaged_count: int = 0
    unknown_count: int = 0
    results: dict[str, IntegrityState] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)
    checksum_updates: dict[str, str] = field(default_factory=dict)  # asset_id -> new_checksum

    @property
    def summary_text(self) -> str:
        return (
            f"已校验: {self.verified_count} · "
            f"已修改: {self.modified_count} · "
            f"缺失: {self.missing_count} · "
            f"外部链接: {self.unmanaged_count}"
        )


def compute_sha256(path: Path, max_bytes: int | None = None) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    bytes_read = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
                bytes_read += len(chunk)
                QThread.yieldCurrentThread()
                if max_bytes and bytes_read >= max_bytes:
                    break
        return h.hexdigest()
    except OSError:
        return None


class IntegrityWorker(QObject):
    progress = Signal(int, int, str)  # (current, total, current_asset_name)
    finished = Signal(IntegrityCheckReport)
    failed = Signal(str)

    def __init__(
        self,
        assets: Sequence[object],
        project_root: Path | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._assets = list(assets)
        self._project_root = project_root

    @Slot()
    def run(self) -> None:
        report = IntegrityCheckReport(total_checked=len(self._assets))

        try:
            for idx, asset in enumerate(self._assets):
                view = asset_view_from_object(asset, project_root=self._project_root)
                self.progress.emit(idx + 1, len(self._assets), view.name)

                path_obj = Path(view.path)
                if not path_obj.is_absolute() and self._project_root:
                    path_obj = self._project_root / path_obj

                if not path_obj.exists():
                    state = IntegrityState.MISSING
                    report.missing_count += 1
                    report.details.append(f"{view.name}: 文件不存在 ({view.path})")
                elif not view.managed:
                    state = IntegrityState.UNMANAGED
                    report.unmanaged_count += 1
                elif view.checksum:
                    # Compute actual SHA-256 and compare
                    actual_hash = compute_sha256(path_obj)
                    if actual_hash == view.checksum:
                        state = IntegrityState.VERIFIED
                        report.verified_count += 1
                    else:
                        state = IntegrityState.MODIFIED
                        report.modified_count += 1
                        report.details.append(f"{view.name}: 校验和不匹配 (预期 {view.checksum[:8]}, 实际 {actual_hash[:8] if actual_hash else 'N/A'})")
                else:
                    # Compute new checksum and record for main-thread assignment
                    new_hash = compute_sha256(path_obj)
                    if new_hash:
                        report.checksum_updates[view.id] = new_hash
                        state = IntegrityState.VERIFIED
                        report.verified_count += 1
                    else:
                        state = IntegrityState.UNKNOWN
                        report.unknown_count += 1

                report.results[view.id] = state

        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.finished.emit(report)
