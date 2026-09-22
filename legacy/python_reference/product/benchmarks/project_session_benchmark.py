#!/usr/bin/env python3
"""Synthetic metadata/session benchmark for large portable projects.

No fixture is retained: every run uses a temporary directory and creates tiny
placeholder files only when necessary.  The script reports medians so it is
useful for local before/after comparisons without pretending to be a native
renderer benchmark.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paleo_workbench.catalog.models import CatalogDocument, DataAsset, DataRun, DataStage, DataVersion
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.store import CatalogStore
from paleo_workbench.catalog.storage import catalog_dir_for
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import (
    ExportArtifact,
    HorizonInterpretationRef,
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
    QualityReport,
    ResourceItem,
)


def _ms(function, repeats: int = 3) -> float:
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        values.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(values)


def _fresh_samples(function, repeats: int) -> float:
    """Median of independent setup+operation samples (never hides a no-op)."""

    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        values.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(values)


def _rss_mb() -> float:
    # Linux reports KiB; macOS reports bytes.  This is diagnostic only.
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024.0 if sys.platform.startswith("linux") else 1024.0 * 1024.0)


def _document(root: Path, count: int) -> ProjectDocument:
    document = ProjectDocument.new(f"Synthetic {count}")
    resources = root / "resources"
    resources.mkdir(parents=True, exist_ok=True)
    for number in range(count):
        document.resources.append(
            ResourceItem(
                id=f"res_{number:06d}",
                name=f"resource-{number:06d}",
                path=(resources / f"item-{number:06d}.las").as_posix(),
                type="well_log" if number % 3 == 0 else "seismic",
                format="las" if number % 3 == 0 else "segy",
                parsed_summary={"samples": number % 1000, "kind": "synthetic"},
            )
        )
        # Exercise the same top-level persistence domains found in a real
        # session without making numerical payloads part of this metadata
        # benchmark.  The payload files remain tiny placeholders by design.
        if number % 20 == 0:
            document.prediction_tasks.append(
                PredictionTask(
                    id=f"pred_{number:06d}",
                    name=f"prediction-{number:06d}",
                    status="complete",
                    result_summary={"resource": number},
                )
            )
        if number % 100 == 0:
            map_id = f"map_{number:06d}"
            document.paleomap_documents.append(
                PaleoMapDocument(
                    id=map_id,
                    name=f"map-{number:06d}",
                    linked_target_horizon=f"H{number % 9}",
                    map_chrome={"scale": 1_000_000},
                )
            )
            document.horizon_interpretations.append(
                HorizonInterpretationRef(
                    id=f"interp_{number:06d}",
                    name=f"horizon-{number:06d}",
                    horizon_key=f"H{number % 9}",
                    artifact_path=(
                        root / "project.artifacts" / "outputs" / f"h-{number:06d}.npz"
                    ).as_posix(),
                )
            )
        if number % 250 == 0:
            document.quality_reports.append(
                QualityReport(
                    id=f"qc_{number:06d}",
                    linked_map_document_id=f"map_{number - number % 100:06d}",
                    status="complete",
                )
            )
            document.export_artifacts.append(
                ExportArtifact(
                    id=f"export_{number:06d}",
                    linked_id=f"map_{number - number % 100:06d}",
                    format="png",
                    output_path=(root / "exports" / f"map-{number:06d}.png").as_posix(),
                )
            )
    return document


def _file_count_and_bytes(root: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for path in root.rglob("*"):
        if path.is_file():
            count += 1
            size += path.stat().st_size
    return count, size


def _seed_catalog(path: Path, count: int) -> None:
    """Create representative canonical catalog metadata without payload I/O."""

    document = CatalogDocument(catalog_revision=1)
    for number in range(count):
        resource_id = f"res_{number:06d}"
        version_id = f"ver_{number:06d}"
        document.assets.append(
            DataAsset(
                id=resource_id,
                name=f"resource-{number:06d}",
                type="well_log" if number % 3 == 0 else "seismic",
                current_version_id=version_id,
                legacy_resource_id=resource_id,
            )
        )
        document.versions.append(
            DataVersion(
                id=version_id,
                asset_id=resource_id,
                version_number=1,
                stage=DataStage.RAW,
                managed=False,
                path=f"/synthetic/{number:06d}.bin",
            )
        )
        if number % 2 == 0:
            document.runs.append(
                DataRun(
                    id=f"run_{number:06d}",
                    operation="synthetic",
                    input_version_ids=[version_id],
                    output_version_ids=[version_id],
                )
            )
    CatalogStore(path).save(document)


def _remove_catalog_index(path: Path) -> None:
    index_path = catalog_dir_for(path) / "catalog.sqlite"
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            Path(f"{index_path}{suffix}").unlink()
        except FileNotFoundError:
            pass


def _catalog_index_ready_from_missing(path: Path) -> None:
    """Time a real rebuild, not a second no-op ``ensure_index_ready`` call."""

    _remove_catalog_index(path)
    service = DataCatalogService.open(path, ensure_index=False, sweep_temp=False)
    try:
        service.ensure_index_ready()
    finally:
        service.close()


def run_scale(count: int, repeats: int) -> dict[str, float | int]:
    with tempfile.TemporaryDirectory(prefix="paleo-project-session-") as raw:
        root = Path(raw)
        path = root / "project.paleo.json"
        document = _document(root, count)
        manager = ProjectManager(path)
        manager.save(document)

        def cold_save_sample() -> None:
            sample = _document(root, count)
            ProjectManager(root / f"cold-{time.monotonic_ns()}.paleo.json").save(sample)

        cold_save_ms = _fresh_samples(cold_save_sample, repeats)
        json_bytes = path.stat().st_size

        # Reopen once so clean/metadata saves exercise the actual session
        # snapshot path used by the application.
        loaded = manager.load()
        clean_before = path.read_bytes()
        clean_save_ms = _ms(lambda: manager.save(loaded), repeats)
        clean_unchanged = int(path.read_bytes() == clean_before)
        clean_payload_written = int(manager.last_save_stats.wrote_project_file) * path.stat().st_size

        loaded.meta.name = f"Synthetic {count} updated"
        before_files, before_bytes = _file_count_and_bytes(root)
        metadata_save_ms = _ms(lambda: manager.save(loaded), 1)
        after_files, after_bytes = _file_count_and_bytes(root)

        open_ms = _ms(lambda: ProjectManager(path).load(), repeats)
        _seed_catalog(path, count)
        catalog_open_deferred_ms = _ms(lambda: _open_deferred(path), repeats)
        index_ready_ms = _fresh_samples(
            lambda: _catalog_index_ready_from_missing(path), repeats
        )
        catalog_path = catalog_dir_for(path) / "catalog.json"
        catalog_bytes = catalog_path.stat().st_size if catalog_path.is_file() else 0

        def metadata_save_as_proxy_sample() -> None:
            # This is intentionally a ProjectManager-only proxy: controller
            # Save As also stages managed artifacts and needs a GUI shell.
            source = ProjectManager(path).load()
            target = root / f"save-as-{time.monotonic_ns()}.paleo.json"
            ProjectManager(target).save(source)

        def project_switch_metadata_proxy_sample() -> None:
            # Persistence-only proxy.  Native page shutdown and worker lifetime
            # are covered by controller regression tests, not this harness.
            ProjectManager(path).load()
            ProjectManager(path).load()

        metadata_save_as_proxy_ms = _fresh_samples(
            metadata_save_as_proxy_sample, repeats
        )
        project_switch_metadata_proxy_ms = _fresh_samples(
            project_switch_metadata_proxy_sample, repeats
        )

        return {
            "records": count,
            "project_json_mb": round(json_bytes / 1024 / 1024, 3),
            "cold_save_ms": round(cold_save_ms, 3),
            "clean_save_ms": round(clean_save_ms, 3),
            "clean_noop": clean_unchanged,
            "clean_payload_written_bytes": clean_payload_written,
            "metadata_save_ms": round(metadata_save_ms, 3),
            "metadata_payload_written_bytes": path.stat().st_size,
            "open_ms": round(open_ms, 3),
            "catalog_open_deferred_ms": round(catalog_open_deferred_ms, 3),
            "index_ready_ms": round(index_ready_ms, 3),
            "metadata_save_as_proxy_ms": round(metadata_save_as_proxy_ms, 3),
            "project_switch_metadata_proxy_ms": round(
                project_switch_metadata_proxy_ms, 3
            ),
            "catalog_json_mb": round(catalog_bytes / 1024 / 1024, 3),
            "save_files_delta": after_files - before_files,
            "save_bytes_delta": after_bytes - before_bytes,
            "peak_rss_mb": round(_rss_mb(), 3),
        }


def _open_deferred(path: Path) -> None:
    service = DataCatalogService.open(path, ensure_index=False, sweep_temp=False)
    service.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, nargs="+", default=[100, 1_000, 10_000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    for count in args.records:
        print(json.dumps(run_scale(count, args.repeats), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
