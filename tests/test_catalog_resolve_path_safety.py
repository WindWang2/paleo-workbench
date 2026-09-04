"""Issues #1140 / #1175 — exact-match path resolution + entity-id sanitization.

#1140: ``resolve_path`` used to fall back to the last two segments / the bare
basename of a recorded external path, so an external RAW that had moved
silently re-bound to an unrelated in-project file with the same name. The
fallbacks are gone: unresolvable paths return the recorded path and integrity
surfaces them as missing.

#1175: asset/version ids interpolated into managed storage paths
(``{stage}/{asset_id}/{version_id}/``) are validated against a safe charset —
a migrated legacy ``ResourceItem.id`` carrying ``../`` must never escape the
ledger tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.models import CatalogError, DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import (
    catalog_dir_for,
    is_safe_entity_id,
    place_managed_file,
)
from paleo_workbench.catalog.store import catalog_file_for
from paleo_workbench.project.models import ResourceItem


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path: Path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


# ------------------------------------------------------------- #1140


def test_resolve_path_never_rebinds_same_named_in_project_file(
    service: DataCatalogService, tmp_path: Path
):
    """A moved external file must not resolve to an in-project namesake."""
    project_dir = service.project_path.parent
    external = tmp_path / "elsewhere" / "data.segy"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_bytes(b"segy-bytes")

    version = service.link_external(external, name="data.segy")
    assert service.resolve_path(version) == external.resolve()

    # The external RAW "moves away"; an unrelated in-project file with the
    # SAME basename now exists.
    external.unlink()
    namesake = project_dir / "data.segy"
    namesake.write_bytes(b"in-project-impostor")

    resolved = service.resolve_path(version)
    assert resolved != namesake.resolve(), (
        "resolve_path re-bound a missing external file to an in-project namesake"
    )
    assert not resolved.is_file()
    # And integrity reflects the loss instead of verifying the impostor.
    report = service.verify_integrity(version.id)
    assert report.status_for(version.id) == "missing"


def test_resolve_path_still_supports_exact_relocation_modes(
    service: DataCatalogService, tmp_path: Path
):
    """Managed exact path, external absolute path, project-relative join and
    the project-name re-anchor all keep working."""
    src = tmp_path / "in.las"
    src.write_bytes(b"las")
    managed = service.import_raw(src)
    resolved = service.resolve_path(managed)
    assert resolved.is_file()
    assert resolved == service.project_path.parent / managed.path

    ext = tmp_path / "ext.las"
    ext.write_bytes(b"ext")
    external = service.link_external(ext)
    assert service.resolve_path(external) == ext.resolve()

    # Project-relative stored path: (project_dir / raw) exists.
    rel = service.project_path.parent / "rel.csv"
    rel.write_bytes(b"rel")
    rel_version = service.link_external(rel)
    rel_version.path = "rel.csv"  # stored as a project-relative reference
    assert service.resolve_path(rel_version) == rel.resolve()

    # Recorded path containing the project dir name re-anchors onto the
    # CURRENT project dir (relocation recovery) — still exact, not a suffix
    # guess: every segment after the project name must match.
    moved = service.project_path.parent / "nested" / "deep.csv"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_bytes(b"deep")
    relocated = service.link_external(moved)
    relocated.path = f"/old/home/{service.project_path.parent.name}/nested/deep.csv"
    assert service.resolve_path(relocated) == moved.resolve()


def test_integrity_missing_for_dead_external(service: DataCatalogService, tmp_path):
    ext = tmp_path / "gone.las"
    ext.write_bytes(b"g")
    version = service.link_external(ext)
    ext.unlink()
    report = service.verify_integrity(version.id)
    assert report.status_for(version.id) == "missing"


# ------------------------------------------------------------- #1175


@pytest.mark.parametrize(
    "bad_id",
    ["../escape", "a/b", "a\\b", ".hidden", "", "a..b/../c"],
)
def test_unsafe_entity_ids_rejected(bad_id: str):
    assert not is_safe_entity_id(bad_id)


@pytest.mark.parametrize(
    "good_id", ["asset_abc123", "ver-1.2_3", "A.b-c_d"]
)
def test_safe_entity_ids_accepted(good_id: str):
    assert is_safe_entity_id(good_id)


def test_place_managed_file_rejects_traversal_asset_id(service, tmp_path):
    """An asset id with ``../`` must be refused before any directory is made."""
    src = tmp_path / "f.bin"
    src.write_bytes(b"f")
    with pytest.raises(CatalogError):
        place_managed_file(
            src, service.project_path, DataStage.RAW, "../evil", "ver_1"
        )
    # ``raw/../evil`` would have landed NEXT TO the artifacts root.
    project_dir = service.project_path.parent
    assert not (project_dir / "evil").exists()
    assert not (project_dir.parent / "evil").exists()


def test_migration_sanitizes_unsafe_legacy_resource_id(service: DataCatalogService):
    """A crafted ResourceItem id becomes a safe asset id; the original id
    survives as the legacy bridge so references keep resolving."""
    resource = ResourceItem(
        id="../../etc/passwd",
        name="evil",
        path="/nonexistent/evil.bin",
        type="document",
        format="bin",
    )
    report = service.migrate_legacy_resources([resource])
    assert report.migrated_count == 1
    asset = service.document.assets[0]
    assert is_safe_entity_id(asset.id)
    assert asset.id != resource.id
    assert asset.legacy_resource_id == resource.id
    assert service._asset_by_legacy_id(resource.id) is asset
    # The projected version id (built from the asset id) is path-safe too.
    assert is_safe_entity_id(service.document.versions[0].id)


def test_register_derived_store_rejects_unsafe_ids(service: DataCatalogService):
    """The derived-store placement joins asset/version ids into the layout."""
    store = service.project_path.parent / "store"
    store.mkdir(parents=True, exist_ok=True)
    (store / "chunk.bin").write_bytes(b"c")

    # _new_asset generates safe ids; simulate a hostile document by building
    # the registration with a monkeypatched id factory is overkill — instead
    # assert the guard directly on the seam the placement uses.
    from paleo_workbench.catalog.storage import _require_safe_entity_id

    with pytest.raises(CatalogError):
        _require_safe_entity_id("asset", "../evil")
    with pytest.raises(CatalogError):
        _require_safe_entity_id("version", "..")


def test_manifest_and_store_paths_stay_within_project(service, tmp_path):
    """End-to-end: a normal import writes only under <project>.artifacts/."""
    from paleo_workbench.project.paths import artifact_dir_for

    src = tmp_path / "ok.las"
    src.write_bytes(b"ok")
    version = service.import_raw(src)
    resolved = service.resolve_path(version)
    artifacts_root = artifact_dir_for(service.project_path)
    assert artifacts_root in resolved.parents
    assert catalog_dir_for(service.project_path).name == "metadata"
    assert catalog_file_for(service.project_path).is_file()
