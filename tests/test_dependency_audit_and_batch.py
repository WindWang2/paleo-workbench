"""I13/I14 — dependency audit, relink suggestions, batch conversion service."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.interchange.batch import BatchConversionService, ConversionJob
from paleo_workbench.interchange.contracts import CancelToken, CancelledError
from paleo_workbench.interchange.dependency_audit import (
    DependencyStatus,
    ExternalDependencyAuditor,
)

from tests import interchange_fixtures as fx


@pytest.fixture()
def catalog(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    yield service
    service.close()


# ---------------------------------------------------------------------------
# Dependency audit
# ---------------------------------------------------------------------------


def test_audit_classifies_valid_unknown_and_missing(catalog, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    known = fx.write_valid_las(outside / "known.las")
    doomed = outside / "gone.las"
    fx.write_valid_las(doomed, rows=3)

    v_known = catalog.link_external(known, name="known", type="well_log", format="las")
    v_missing = catalog.link_external(doomed, name="gone", type="well_log", format="las")
    doomed.unlink()  # the reference is now dangling

    auditor = ExternalDependencyAuditor(catalog)
    report = auditor.audit()
    by_version = {r.version_id: r for r in report.records}
    assert by_version[v_known.id].status is DependencyStatus.UNKNOWN  # no hash recorded
    assert by_version[v_missing.id].status is DependencyStatus.MISSING


def test_audit_detects_changed_content(catalog, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    source = fx.write_valid_las(outside / "mutate.las")
    version = catalog.import_raw(source, name="mut", type="well_log", format="las")
    # managed copies are hashed: flip bytes in place (checksum becomes stale)
    managed = Path(catalog.resolve_path(version))
    managed.chmod(0o644)
    managed.write_bytes(bytes([b ^ 0xFF for b in managed.read_bytes()]))

    auditor = ExternalDependencyAuditor(catalog)
    report = auditor.audit()
    record = next(r for r in report.records if r.version_id == version.id)
    assert record.status is DependencyStatus.CHANGED
    assert not report.ok


def test_relink_candidates_require_content_match(catalog, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    source = fx.write_valid_las(outside / "original.las", rows=12)
    version = catalog.import_raw(source, name="orig", type="well_log", format="las")
    managed = Path(catalog.resolve_path(version))
    managed.unlink()

    auditor = ExternalDependencyAuditor(catalog)
    report = auditor.audit()
    record = report.records[0]
    assert record.status is DependencyStatus.MISSING

    search = tmp_path / "search"
    (search / "a").mkdir(parents=True)
    # same basename, WRONG content → size differs → never a candidate
    fx.write_valid_las(search / "a" / "original.las", rows=40)
    # different basename, exact same content → verified candidate
    fx.write_valid_las(search / "a" / "renamed-copy.las", rows=12)

    auditor.attach_candidates(report, [search])
    assert record.status is DependencyStatus.RELINK_CANDIDATE
    verified = [c for c in record.relink_candidates if c.sha256 == record.expected_sha256]
    assert verified, "内容一致的候选（即使不同名）必须被识别"
    assert all(c.size_bytes == record.expected_size for c in record.relink_candidates)


def test_relink_basename_alone_is_never_a_candidate(catalog, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    source = fx.write_valid_las(outside / "orig.las", rows=10)
    version = catalog.import_raw(source, name="o", type="well_log", format="las")
    Path(catalog.resolve_path(version)).unlink()

    search = tmp_path / "search"
    search.mkdir()
    # same name, different content (size differs)
    fx.write_valid_las(search / "orig.las", rows=77)

    auditor = ExternalDependencyAuditor(catalog)
    report = auditor.audit()
    record = report.records[0]
    auditor.attach_candidates(report, [search])
    assert record.relink_candidates == []
    assert record.status is DependencyStatus.MISSING


def test_apply_relink_creates_new_link_version(catalog, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    source = fx.write_valid_las(outside / "orig.las", rows=8)
    version = catalog.import_raw(source, name="o", type="well_log", format="las")
    managed = Path(catalog.resolve_path(version))
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    moved = relocated / "orig.las"
    managed.rename(moved)

    auditor = ExternalDependencyAuditor(catalog)
    report = auditor.audit()
    record = report.records[0]
    assert record.status is DependencyStatus.MISSING
    record.relink_candidates = auditor.find_relink_candidates(record, [relocated])
    verified = [c for c in record.relink_candidates if c.sha256 == record.expected_sha256]
    assert verified
    new_version = auditor.apply_relink(record, verified[0])
    assert new_version.id != version.id
    assert new_version.managed is False
    asset = catalog.get_asset(new_version.asset_id)
    assert asset.metadata.get("relinked_from") == version.id

    # size-only candidate requires explicit human confirmation
    size_only = next(
        (c for c in record.relink_candidates if c.sha256 is None), None
    )
    if size_only is not None:
        with pytest.raises(ValueError):
            auditor.apply_relink(record, size_only)


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------


def test_batch_converts_geojson_and_isolates_failures(tmp_path):
    sources = [fx.write_geojson(tmp_path / f"f{i}.geojson", features=2) for i in range(5)]
    broken = tmp_path / "broken.geojson"
    broken.write_text("{ truncated", encoding="utf-8")
    sources.append(broken)

    service = BatchConversionService(max_workers=2)
    result = service.convert(
        [ConversionJob(source=s, target_format="geojson") for s in sources],
        output_dir=tmp_path / "out",
    )
    summary = result.summary()
    assert summary["total"] == 6
    assert summary["converted"] == 5
    assert summary["failed"] == 1  # isolated, did not abort the batch
    assert sorted(r.source for r in result.results) == sorted(str(s) for s in sources)
    # deterministic naming; the failed source produces no output file
    outs = sorted(p.name for p in (tmp_path / "out").glob("*.geojson"))
    assert outs == ["f0.geojson", "f1.geojson", "f2.geojson", "f3.geojson", "f4.geojson"]


def test_batch_naming_collision_gets_deterministic_suffix(tmp_path):
    a = tmp_path / "sub1"
    b = tmp_path / "sub2"
    a.mkdir()
    b.mkdir()
    fx.write_geojson(a / "same.geojson")
    fx.write_geojson(b / "same.geojson")
    service = BatchConversionService(max_workers=1)
    result = service.convert(
        [ConversionJob(source=a / "same.geojson", target_format="geojson"),
         ConversionJob(source=b / "same.geojson", target_format="geojson")],
        output_dir=tmp_path / "out",
    )
    names = sorted(p.name for p in (tmp_path / "out").glob("*.geojson"))
    assert names == ["same-2.geojson", "same.geojson"]


def test_batch_cancellation_marks_remaining_cancelled(tmp_path):
    sources = [fx.write_geojson(tmp_path / f"c{i}.geojson", features=1) for i in range(8)]
    token = CancelToken()

    service = BatchConversionService(max_workers=1)
    calls = {"n": 0}

    def progress(done, total, current):
        calls["n"] += 1
        if done == 3:
            token.cancel("user stopped")

    result = service.convert(
        [ConversionJob(source=s, target_format="geojson") for s in sources],
        output_dir=tmp_path / "out",
        cancel=token,
        progress=progress,
    )
    summary = result.summary()
    assert result.cancelled
    assert summary["converted"] == 3
    assert summary["cancelled"] == 5
    assert summary["was_cancelled"] is True


def test_batch_estimate_and_empty(tmp_path):
    source = fx.write_geojson(tmp_path / "e.geojson")
    service = BatchConversionService()
    total, warnings = service.estimate(
        [ConversionJob(source=source, target_format="geojson")], output_dir=tmp_path / "o"
    )
    assert total > 0 and warnings == []
    result = service.convert([], output_dir=tmp_path / "o")
    assert result.summary()["total"] == 0


def test_batch_scale_1000_files_no_fd_leak(tmp_path):
    """1000-file metadata batch: completes, no FD leak, deterministic output."""
    sources = []
    for i in range(1000):
        source = tmp_path / f"bulk{i % 40}.geojson"
        if not source.exists():
            fx.write_geojson(source, features=1)
        sources.append(source)
    jobs = [ConversionJob(source=s, target_format="geojson") for s in sources]

    def fd_count() -> int:
        try:
            return len(os.listdir("/proc/self/fd"))
        except OSError:
            return -1

    before = fd_count()
    service = BatchConversionService(max_workers=2)
    result = service.convert(jobs, output_dir=tmp_path / "bulk-out", verify=False)
    after = fd_count()

    summary = result.summary()
    assert summary["total"] == 1000
    assert summary["converted"] == 1000
    assert summary.get("failed", 0) == 0
    if before >= 0 and after >= 0:
        assert after - before < 50, f"FD 泄漏: {before} → {after}"
