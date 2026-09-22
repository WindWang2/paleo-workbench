"""Version-level lineage completeness tests.

Pins the invariant that every produced (non-RAW-head) version is traceable to
its inputs through the VERSION graph (``parent_version_ids``), not only via
run records: ``register_result_asset`` must copy the run's inputs into the
new version's parents so OUTPUT → RAW reverse traversal works.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str, payload: bytes = b"data") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def test_register_result_asset_copies_run_inputs_to_parents(service, tmp_path):
    raw = service.import_raw(_make_source(tmp_path, "raw.las", b"raw"))
    run = service.register_run(
        "inference", input_version_ids=[raw.id], parameters={"model": "demo-v1"}
    )

    result = service.register_result_asset(
        name="facies-prediction.json",
        type="prediction",
        format="json",
        asset_metadata=None,
        source_path=_make_source(tmp_path, "result.json", b"{}"),
        stage=DataStage.DERIVED,
        run_id=run.id,
    )

    lineage = service.get_lineage(result.id)
    assert [v.id for v in lineage["parents"]] == [raw.id]
    # The run record is also linked (outputs) and reachable from the version.
    assert result.run_id == run.id
    assert result.id in service.get_run(run.id).output_version_ids


def test_register_result_asset_without_run_has_no_parents(service, tmp_path):
    result = service.register_result_asset(
        name="standalone.bin",
        type="unknown",
        format="bin",
        asset_metadata=None,
        source_path=_make_source(tmp_path, "standalone.bin", b"x"),
        stage=DataStage.INTERMEDIATE,
    )
    assert service.get_lineage(result.id)["parents"] == []


def test_output_to_raw_chain_survives_export(service, tmp_path):
    """Full chain: RAW → run → DERIVED → run → OUTPUT; reverse traversal
    from the OUTPUT version reaches the RAW input through parent edges."""
    raw = service.import_raw(_make_source(tmp_path, "raw.las", b"raw"))
    derive_run = service.register_run("derive", input_version_ids=[raw.id])
    derived = service.register_version(
        raw.asset_id,
        _make_source(tmp_path, "derived.npy", b"derived"),
        DataStage.DERIVED,
        parent_version_ids=[raw.id],
        run_id=derive_run.id,
    )
    export_run = service.register_run(
        "export", input_version_ids=[derived.id], parameters={"format": "png"}
    )
    output = service.register_result_asset(
        name="map.png",
        type="map",
        format="png",
        asset_metadata=None,
        source_path=_make_source(tmp_path, "map.png", b"png"),
        stage=DataStage.OUTPUT,
        run_id=export_run.id,
    )

    # Reverse walk: OUTPUT → parents → DERIVED → parents → RAW.
    chain = []
    cursor = output
    while cursor is not None:
        chain.append(cursor)
        parents = service.get_lineage(cursor.id)["parents"]
        cursor = parents[0] if parents else None
    assert [v.stage for v in chain] == [
        DataStage.OUTPUT,
        DataStage.DERIVED,
        DataStage.RAW,
    ]
    assert chain[-1].id == raw.id


# --- review-round hardening ---------------------------------------------------


def test_purged_run_inputs_do_not_poison_new_versions(service, tmp_path):
    """A result registered against a run whose inputs were purged must not be
    born with broken lineage (parents are filtered to existing versions; the
    run record keeps the full historical reference list)."""
    raw = service.import_raw(_make_source(tmp_path, "raw.las", b"raw"))
    run = service.register_run("inference", input_version_ids=[raw.id])
    service.trash_version(raw.id)
    service.purge_trashed()

    result = service.register_result_asset(
        name="late.json",
        type="prediction",
        format="json",
        asset_metadata=None,
        source_path=_make_source(tmp_path, "late.json", b"{}"),
        stage=DataStage.DERIVED,
        run_id=run.id,
    )

    assert service.get_lineage(result.id)["parents"] == []
    report = service.audit()
    assert report.by_kind("broken_lineage") == []
    # The run itself keeps the purge-retained reference (LOW, informational).
    assert report.by_kind("broken_run_link")


def test_repeated_qc_reports_share_one_asset(service, tmp_path):
    """Re-running QC on the same document appends a version to the SAME
    report asset instead of spawning single-version assets."""
    from paleo_workbench.catalog import CoreCatalogAdapter
    from paleo_workbench.catalog.lifecycle import register_qc_run

    adapter = CoreCatalogAdapter(service)
    raw = service.import_raw(_make_source(tmp_path, "raw.las", b"raw"))
    for i in range(2):
        report_file = _make_source(tmp_path, f"qc{i}.json", b'{"ok": true}')
        register_qc_run(
            name=f"QC demo-doc",
            input_version_ids=[raw.id],
            domain_task_id="doc-1",
            report_path=str(report_file),
            catalog=adapter,
        )

    qc_assets = [a for a in service.list_assets() if a.name == "QC demo-doc"]
    assert len(qc_assets) == 1
    versions = service.list_versions(qc_assets[0].id)
    assert len(versions) == 2
