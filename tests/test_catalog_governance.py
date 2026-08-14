"""Metadata governance tests: vocabularies, update_asset_metadata, search.

Governance fields live on the ASSET metadata dict (validated + normalized);
VERSION metadata stays immutable with the version — there is deliberately no
version-level update API. Search covers both the SQLite index path
(json_extract) and the canonical document-scan fallback.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import DataCatalogService, GovernanceError
from paleo_workbench.catalog.governance import (
    GOVERNANCE_KEYS,
    governance_display,
    governance_display_rows,
    governance_values,
    normalize_governance_patch,
    normalize_governance_value,
)


def _project_file(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_project_file(tmp_path))
    (tmp_path / "raw.sgy").write_bytes(b"seismic")
    version = svc.import_raw(tmp_path / "raw.sgy", name="seismic.sgy", type="seismic")
    yield svc, version
    svc.close()


# --- vocabulary normalization -------------------------------------------------


def test_governance_keys_are_the_standard_set():
    assert set(GOVERNANCE_KEYS) == {
        "source",
        "region",
        "creator",
        "discipline",
        "confidence",
        "review_status",
    }


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("confidence", "高", "high"),
        ("confidence", "A", "high"),
        ("confidence", "medium", "medium"),
        ("review_status", "待审核", "pending_review"),
        ("review_status", "approved", "approved"),
        ("discipline", "well_log", "well_log"),
        ("discipline", "paleomap", "paleomap"),
        ("source", "  甲方 移交 ", "甲方 移交"),
        ("region", "塔里木盆地", "塔里木盆地"),
    ],
)
def test_normalize_governance_value(key, raw, expected):
    assert normalize_governance_value(key, raw) == expected


def test_normalize_rejects_unknown_vocabulary_value():
    with pytest.raises(GovernanceError):
        normalize_governance_value("confidence", "extreme")
    with pytest.raises(GovernanceError):
        normalize_governance_value("review_status", "final")
    with pytest.raises(GovernanceError):
        normalize_governance_value("not_a_field", "x")


def test_empty_value_normalizes_to_blank():
    assert normalize_governance_value("confidence", "") == ""
    assert normalize_governance_value("region", None) == ""


def test_normalize_patch_passes_through_non_governance_keys():
    patch = normalize_governance_patch(
        {"confidence": "高", "custom_note": "keep me"}
    )
    assert patch == {"confidence": "high", "custom_note": "keep me"}


def test_governance_display_rows_are_ordered_and_labeled():
    rows = governance_display_rows({"region": "塔里木", "confidence": "low"})
    assert rows == [("区域", "塔里木"), ("可信等级", "低")]
    assert governance_display("review_status", "pending_review") == "待审核"


# --- update_asset_metadata -----------------------------------------------------


def test_update_asset_metadata_persists_and_bumps_updated_at(service):
    svc, version = service
    asset = svc.get_asset(version.asset_id)
    before = asset.updated_at
    asset.updated_at = "2000-01-01T00:00:00"  # force a visible bump
    svc.update_asset_metadata(
        version.asset_id,
        {"region": "塔里木", "creator": "王工", "confidence": "高", "review_status": "待审核"},
    )
    refreshed = svc.get_asset(version.asset_id)
    assert refreshed.metadata["region"] == "塔里木"
    assert refreshed.metadata["confidence"] == "high"
    assert refreshed.metadata["review_status"] == "pending_review"
    assert refreshed.updated_at != "2000-01-01T00:00:00"
    assert governance_values(refreshed.metadata)["confidence"] == "high"


def test_update_asset_metadata_is_idempotent_without_write(service):
    svc, version = service
    svc.update_asset_metadata(version.asset_id, {"region": "塔里木"})
    revision = svc.document.catalog_revision
    svc.update_asset_metadata(version.asset_id, {"region": "塔里木"})
    assert svc.document.catalog_revision == revision  # no-op → no canonical save


def test_update_asset_metadata_rejects_invalid_value_and_writes_nothing(service):
    svc, version = service
    revision = svc.document.catalog_revision
    with pytest.raises(GovernanceError):
        svc.update_asset_metadata(version.asset_id, {"confidence": "extreme"})
    assert svc.document.catalog_revision == revision
    assert "confidence" not in svc.get_asset(version.asset_id).metadata


def test_update_asset_metadata_clearing_a_field(service):
    svc, version = service
    svc.update_asset_metadata(version.asset_id, {"region": "塔里木"})
    svc.update_asset_metadata(version.asset_id, {"region": ""})
    assert "region" not in svc.get_asset(version.asset_id).metadata


def test_update_asset_metadata_unknown_asset_raises(service):
    svc, _version = service
    with pytest.raises(Exception):
        svc.update_asset_metadata("asset-missing", {"region": "x"})


def test_version_metadata_has_no_update_api(service):
    """Version immutability: committed version metadata is never writable.

    There is no service method to patch version metadata; the sanctioned
    change path is a new version (e.g. promote with reviewer note).
    """
    svc, version = service
    assert not hasattr(svc, "update_version_metadata")
    with pytest.raises(Exception):
        # Direct document mutation is NOT the API; registering over the same
        # version id must stay refused (immutable version doctrine).
        svc.register_version(
            version.asset_id,
            Path(version.path),
            version.stage,
            version_id=version.id,
        )


# --- metadata search ------------------------------------------------------------


def test_search_assets_by_metadata(service):
    svc, version = service
    (svc.project_path.parent / "second.las").write_bytes(b"second")
    other = svc.import_raw(
        svc.project_path.parent / "second.las", name="second.las", type="well_log"
    )
    svc.update_asset_metadata(version.asset_id, {"region": "塔里木", "confidence": "high"})
    svc.update_asset_metadata(other.asset_id, {"region": "四川"})
    assert [a.id for a in svc.search_assets(metadata={"region": "塔里木"})] == [
        version.asset_id
    ]
    assert [a.id for a in svc.search_assets(metadata={"confidence": "high"})] == [
        version.asset_id
    ]
    assert svc.search_assets(metadata={"region": "鄂尔多斯"}) == []
    # Multiple pairs AND together.
    assert [
        a.id
        for a in svc.search_assets(metadata={"region": "塔里木", "confidence": "low"})
    ] == []


def test_search_assets_metadata_scan_fallback_matches_index(service):
    svc, version = service
    svc.update_asset_metadata(version.asset_id, {"region": "塔里木"})
    from_index = [a.id for a in svc.search_assets(metadata={"region": "塔里木"})]
    svc._index.reset()  # force the canonical document-scan branch
    from_scan = [a.id for a in svc.search_assets(metadata={"region": "塔里木"})]
    assert from_index == from_scan == [version.asset_id]
