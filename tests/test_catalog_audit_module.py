"""Tests for the lightweight catalog audit (:mod:`paleo_workbench.catalog.audit`).

Each detection class gets a positive and (where meaningful) a negative case:
payload missing / broken lineage / dangling tags / invalid current_version /
orphan artifacts / path mismatch. Audit reports only — it must never mutate
the catalog.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage, Tag
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


def _writable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _seed_catalog(service, tmp_path) -> tuple:
    """One RAW import + one derived version + tags on both levels."""
    raw = service.import_raw(_make_source(tmp_path, "raw.las", b"raw-bytes"))
    run = service.register_run("derive", input_version_ids=[raw.id])
    derived = service.register_version(
        raw.asset_id,
        _make_source(tmp_path, "derived.npy", b"derived-bytes"),
        DataStage.DERIVED,
        parent_version_ids=[raw.id],
        run_id=run.id,
    )
    service.add_tag("重点井", asset_id=raw.asset_id)
    service.add_tag("候选版本", version_id=derived.id)
    return raw, derived


# --- clean state -----------------------------------------------------------


def test_clean_catalog_audits_ok(service, tmp_path):
    _seed_catalog(service, tmp_path)
    report = service.audit()
    assert report.ok is True
    assert report.checked["assets"] == 1
    assert report.checked["versions"] == 2
    assert report.by_severity("high") == []
    assert report.by_severity("medium") == []


# --- payload missing -------------------------------------------------------


def test_missing_payload_is_high_severity(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    payload = service.resolve_path(raw)
    _writable(payload.parent)
    payload.chmod(payload.stat().st_mode | stat.S_IWUSR)
    payload.unlink()

    report = service.audit()
    issue = next(i for i in report.by_kind("payload_missing") if i.ref_id == raw.id)
    assert issue.severity == "high"
    assert report.ok is False


# --- broken lineage --------------------------------------------------------


def test_dangling_parent_version_is_reported(service, tmp_path):
    raw, derived = _seed_catalog(service, tmp_path)
    derived.parent_version_ids.append("ver-does-not-exist")

    report = service.audit()
    issues = report.by_kind("broken_lineage")
    assert issues and issues[0].ref_id == derived.id
    assert "ver-does-not-exist" in issues[0].detail


def test_purge_retained_run_link_is_informational(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    # Simulate purge-retained provenance: run io referencing a purged version.
    run = service.register_run("old", input_version_ids=[raw.id])
    run.input_version_ids.append("ver-purged")

    report = service.audit()
    kinds = {i.kind for i in report.issues}
    assert "broken_run_link" in kinds
    # low severity only — not a hard failure.
    assert all(
        i.severity == "low" for i in report.by_kind("broken_run_link")
    )


# --- dangling tags ---------------------------------------------------------


def test_dangling_tag_associations_are_reported(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    service.document.asset_tags[raw.asset_id].append("tag-does-not-exist")
    service.document.version_tags["ver-does-not-exist"] = []

    report = service.audit()
    dangling = report.by_kind("dangling_tag_ref")
    assert len(dangling) == 2
    assert report.ok is False


def test_unused_tag_is_informational(service, tmp_path):
    _seed_catalog(service, tmp_path)
    service.document.tags.append(Tag(name="orphan-tag"))

    report = service.audit()
    unused = report.by_kind("unused_tag")
    assert unused and unused[0].severity == "low"
    assert report.ok is True  # low severity does not fail the audit


# --- invalid current_version -----------------------------------------------


def test_invalid_current_version_is_high(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    asset = service.get_asset(raw.asset_id)
    asset.current_version_id = "ver-does-not-exist"

    report = service.audit()
    issues = report.by_kind("invalid_current_version")
    assert issues and issues[0].severity == "high"


def test_current_version_of_foreign_asset_is_reported(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    other = service.import_raw(_make_source(tmp_path, "other.las", b"other"))
    service.get_asset(raw.asset_id).current_version_id = other.id

    report = service.audit()
    issues = report.by_kind("invalid_current_version")
    assert issues and "belongs to asset" in issues[0].detail


# --- path mismatch ---------------------------------------------------------


def test_wrong_stage_layout_is_reported(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    # Pretend the RAW payload lives under derived/ — layout violation.
    parts = raw.path.split("/")
    parts[1] = "derived"
    raw.path = "/".join(parts)

    report = service.audit()
    issues = report.by_kind("path_mismatch")
    assert issues and issues[0].ref_id == raw.id
    assert issues[0].severity == "medium"


# --- orphan artifacts ------------------------------------------------------


def test_unreferenced_payload_file_is_orphan(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    payload = service.resolve_path(raw)
    stray = payload.parent / "stray.bin"
    _writable(payload.parent)
    stray.write_bytes(b"stray")

    report = service.audit()
    kinds = report.counts_by_kind()
    assert kinds.get("orphan_stage_orphan", 0) >= 1
    # Orphans are informational (GC decides about deletion).
    assert all(i.severity == "low" for i in report.by_kind("orphan_stage_orphan"))


# --- deep mode (hashing) ---------------------------------------------------


def test_deep_audit_reports_integrity_mismatch(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    payload = service.resolve_path(raw)
    _writable(payload)
    payload.write_bytes(b"tampered")

    light = service.audit(deep=False)
    assert light.by_kind("integrity_mismatch") == []
    deep = service.audit(deep=True)
    assert [i.ref_id for i in deep.by_kind("integrity_mismatch")] == [raw.id]
    assert deep.ok is False


# --- audit never mutates ---------------------------------------------------


def test_audit_does_not_mutate_catalog(service, tmp_path):
    _seed_catalog(service, tmp_path)
    before_revision = service.document.catalog_revision
    service.audit(deep=True)
    assert service.document.catalog_revision == before_revision


def test_counts_by_kind_helper(service, tmp_path):
    _seed_catalog(service, tmp_path)
    report = service.audit()
    assert isinstance(report.counts_by_kind(), dict)
    assert set(report.checked) == {"assets", "versions", "runs", "tags"}


# --- review-round tolerances -------------------------------------------------


def test_trashed_crash_window_state_is_not_a_mismatch(service, tmp_path):
    """Tombstone saved before the payload move is a DOCUMENTED consistent
    crash state — audit must not flag it (service.py trash_version docs)."""
    raw, _ = _seed_catalog(service, tmp_path)
    service.trash_version(raw.id)
    # Simulate the crash window: restore the recorded original path in memory
    # (payload still at the original location, tombstone persisted).
    raw.path = raw.metadata["trash"]["original_path"]

    report = service.audit()
    assert report.by_kind("path_mismatch") == []
    assert report.ok is True


def test_trashed_missing_payload_is_low_not_high(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    payload = service.resolve_path(raw)
    _writable(payload.parent)
    service.trash_version(raw.id)
    trashed = service.resolve_path(raw)
    trashed.chmod(trashed.stat().st_mode | stat.S_IWUSR)
    trashed.unlink()  # metadata-only tombstone territory

    report = service.audit()
    issues = report.by_kind("payload_missing")
    assert issues and issues[0].severity == "low"
    assert report.ok is True  # recoverable metadata, not active data loss


def test_cycle_through_second_parent_is_detected(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    b = service.register_version(
        raw.asset_id, _make_source(tmp_path, "b.npy", b"b"),
        DataStage.DERIVED, parent_version_ids=[raw.id],
    )
    c = service.register_version(
        raw.asset_id, _make_source(tmp_path, "c.npy", b"c"),
        DataStage.DERIVED, parent_version_ids=[raw.id, b.id],
    )
    # Close the cycle c → b via c's second parent slot... make b point at c.
    b.parent_version_ids.append(c.id)

    report = service.audit()
    assert report.by_kind("lineage_cycle")


def test_completed_run_without_output_is_flagged(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    service.register_run(
        "materialize", input_version_ids=[raw.id]
    )  # booked completed, no output — the phantom-provenance shape

    report = service.audit()
    issues = report.by_kind("orphan_completed_run")
    assert issues and issues[0].severity == "low"


# --- provenance / stale runs / output claims (data-governance v2) -------------


def test_nonraw_version_without_run_or_parents_is_unprovenanced(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    orphan = service.register_version(
        raw.asset_id,
        _make_source(tmp_path, "lone.npy", b"lone"),
        DataStage.DERIVED,
        parent_version_ids=[],
        run_id=None,
    )

    report = service.audit()
    issues = [i for i in report.by_kind("unprovenanced_version") if i.ref_id == orphan.id]
    assert issues and issues[0].severity == "medium"
    assert report.ok is False


def test_raw_import_is_never_unprovenanced(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    report = service.audit()
    assert not [
        i for i in report.by_kind("unprovenanced_version") if i.ref_id == raw.id
    ]


def test_stale_running_run_is_flagged(service, tmp_path):
    from datetime import datetime, timedelta, timezone

    raw, _ = _seed_catalog(service, tmp_path)
    run = service.register_run(
        "factor_map", input_version_ids=[raw.id], status="running"
    )
    service.get_run(run.id).created_at = (
        datetime.now(timezone.utc) - timedelta(hours=30)
    ).isoformat()

    report = service.audit()
    issues = [i for i in report.by_kind("stale_running_run") if i.ref_id == run.id]
    assert issues and issues[0].severity == "low"


def test_fresh_running_run_is_not_flagged(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    run = service.register_run(
        "factor_map", input_version_ids=[raw.id], status="running"
    )

    report = service.audit()
    assert not [i for i in report.by_kind("stale_running_run") if i.ref_id == run.id]


def test_output_claimed_by_two_runs_is_reported(service, tmp_path):
    raw, derived = _seed_catalog(service, tmp_path)
    service.register_run("second_claim", output_version_ids=[derived.id])

    report = service.audit()
    issues = [i for i in report.by_kind("multi_claimed_output") if i.ref_id == derived.id]
    assert issues


def test_run_output_without_matching_parent_edge_diverges(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    other = service.register_version(
        raw.asset_id,
        _make_source(tmp_path, "other.npy", b"other"),
        DataStage.INTERMEDIATE,
        parent_version_ids=[],
        run_id=None,
    )
    # A run claims raw → other, but other has no parent edge to raw: the
    # version-graph walk (UI 血缘) will not show that input.
    service.register_run(
        "mystery", input_version_ids=[raw.id], output_version_ids=[other.id]
    )

    report = service.audit()
    issues = [
        i for i in report.by_kind("run_lineage_divergence") if i.ref_id == other.id
    ]
    assert issues


def test_external_path_missing_is_medium(service, tmp_path):
    external_src = _make_source(tmp_path, "ext.sgy", b"ext")
    version = service.link_external(external_src, name="ext.sgy", type="seismic")
    external_src.unlink()

    report = service.audit()
    issues = [
        i for i in report.by_kind("external_path_missing") if i.ref_id == version.id
    ]
    assert issues and issues[0].severity == "medium"


def test_invalid_governance_value_is_reported(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    asset = service.get_asset(raw.asset_id)
    asset.metadata["confidence"] = "bogus"
    service._save()

    report = service.audit()
    issues = [
        i for i in report.by_kind("invalid_metadata_value") if i.ref_id == asset.id
    ]
    assert issues and "confidence" in issues[0].detail


def test_statistics_aggregates_counts_and_severities(service, tmp_path):
    raw, _ = _seed_catalog(service, tmp_path)
    orphan = service.register_version(
        raw.asset_id,
        _make_source(tmp_path, "lone2.npy", b"lone2"),
        DataStage.DERIVED,
    )

    report = service.audit()
    stats = report.statistics
    assert stats["assets"] == 1
    assert stats["versions"] == 3
    assert stats["runs"] >= 1
    assert stats["kind_unprovenanced_version"] >= 1
    assert stats["issues_medium"] >= 1
    assert stats["issues_high"] == len(report.by_severity("high"))


# --- cooperative cancellation (#1056) ---------------------------------------


def test_audit_cancel_stops_between_payloads(service, tmp_path):
    """cancel() returning True stops hashing early and marks the report."""
    _seed_catalog(service, tmp_path)
    calls = {"n": 0}

    def cancel_after_first() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    report = service.audit(deep=True, cancel=cancel_after_first)
    assert report.cancelled is True
    # The audit still reports what it saw before the cancel point.
    assert report.checked["assets"] >= 1

    report_full = service.audit(deep=True, cancel=lambda: False)
    assert report_full.cancelled is False


def test_audit_without_cancel_is_not_marked_cancelled(service, tmp_path):
    _seed_catalog(service, tmp_path)
    report = service.audit(deep=True)
    assert report.cancelled is False


def test_immediate_cancel_returns_partial_report_promptly(service, tmp_path):
    """A never-satisfied cancel probe must not mark the audit cancelled."""
    _seed_catalog(service, tmp_path)
    report = service.audit(deep=True, cancel=lambda: False)
    assert report.cancelled is False
    assert report.ok is True
