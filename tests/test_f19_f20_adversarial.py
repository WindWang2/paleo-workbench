"""Adversarial stress test harness for Milestone 5: Features F19 (Immutability) & F20 (Storage & Dual-Tier SQLite).

Challenger test suite validating:
1. Direct file overwrites on managed payloads (permission check, read-only bits, working copy isolation).
2. Re-registration of identical version IDs with differing payloads (ImmutableVersionError / FileExistsError).
3. Mid-session SQLite corruption / zeroing out and self-healing recovery via CatalogIndex.sync() / rebuild().
4. High-concurrency worker thread database queries during catalog sync and rebuild cycles.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from paleo_workbench.catalog.db import CatalogIndex, ThreadSafeCatalogSession
from paleo_workbench.catalog.models import (
    CatalogDocument,
    CatalogError,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
    ImmutableVersionError,
    Tag,
)
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import (
    blob_path,
    create_working_copy,
    ensure_catalog_layout,
    has_blob,
    place_managed_file,
    restore_payload,
    trash_payload,
)


# ===========================================================================
# Fixtures & Helpers
# ===========================================================================

def make_sample_document(catalog_revision: int = 10) -> CatalogDocument:
    """Construct a populated CatalogDocument with assets, versions, runs, tags, lineage."""
    return CatalogDocument(
        catalog_revision=catalog_revision,
        assets=[
            DataAsset(id="asset_alpha", name="Alpha Well Log", type="well_log"),
            DataAsset(id="asset_beta", name="Beta Surface Grid", type="surface_grid"),
            DataAsset(id="asset_gamma", name="Gamma Contours", type="contour_map"),
        ],
        versions=[
            DataVersion(
                id="ver_alpha_1",
                asset_id="asset_alpha",
                version_number=1,
                stage=DataStage.RAW,
                path="raw/asset_alpha/ver_alpha_1/alpha.las",
                sha256="a" * 64,
                size_bytes=1024,
            ),
            DataVersion(
                id="ver_beta_1",
                asset_id="asset_beta",
                version_number=1,
                stage=DataStage.DERIVED,
                path="derived/asset_beta/ver_beta_1/grid.npy",
                sha256="b" * 64,
                size_bytes=2048,
                parent_version_ids=["ver_alpha_1"],
                run_id="run_kriging_1",
            ),
            DataVersion(
                id="ver_gamma_1",
                asset_id="asset_gamma",
                version_number=1,
                stage=DataStage.OUTPUT,
                path="outputs/asset_gamma/ver_gamma_1/contours.json",
                sha256="c" * 64,
                size_bytes=4096,
                parent_version_ids=["ver_beta_1"],
                run_id="run_contour_1",
            ),
        ],
        runs=[
            DataRun(
                id="run_kriging_1",
                operation="kriging_interpolation",
                generator="paleo.mapping.pipeline",
                parameters={"variogram": "spherical", "range": 5000.0},
                input_version_ids=["ver_alpha_1"],
                output_version_ids=["ver_beta_1"],
            ),
            DataRun(
                id="run_contour_1",
                operation="marching_squares",
                generator="paleo.mapping.contour",
                parameters={"interval": 10.0},
                input_version_ids=["ver_beta_1"],
                output_version_ids=["ver_gamma_1"],
            ),
        ],
        tags=[
            Tag(id="tag_qc", name="QC Passed", display_name="QC Passed"),
            Tag(id="tag_prod", name="Production", display_name="Production Ready"),
        ],
        asset_tags={
            "asset_alpha": ["tag_qc"],
            "asset_beta": ["tag_qc", "tag_prod"],
            "asset_gamma": ["tag_prod"],
        },
        version_tags={
            "ver_beta_1": ["tag_prod"],
            "ver_gamma_1": ["tag_prod"],
        },
    )


# ===========================================================================
# Vector 1: Direct file overwrites on managed payloads (F19 Immutability)
# ===========================================================================

class TestPayloadImmutabilityAndPermissions:
    """Stress tests verifying physical read-only mode bits, write protection, and working copy isolation."""

    @pytest.mark.parametrize("stage", [
        DataStage.RAW,
        DataStage.DERIVED,
        DataStage.INTERMEDIATE,
        DataStage.OUTPUT,
    ])
    def test_direct_file_overwrites_blocked_across_all_stages(self, tmp_path: Path, stage: DataStage):
        """Managed payloads in all stages must have write permissions stripped (0o444/0o400) and block in-place writes."""
        project = tmp_path / "test_proj"
        src_file = tmp_path / "source.dat"
        payload_content = b"ORIGINAL_PAYLOAD_IMMUTABLE_DATA_12345"
        src_file.write_bytes(payload_content)

        rel_path, size, digest = place_managed_file(
            src_file, project, stage, "asset_test", "ver_100"
        )
        placed_path = tmp_path / rel_path
        assert placed_path.is_file()
        assert placed_path.read_bytes() == payload_content

        # Verify mode bits do not contain write bits (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        file_mode = placed_path.stat().st_mode
        assert not (file_mode & stat.S_IWUSR), f"Write bit (USR) present on {placed_path}"
        assert not (file_mode & stat.S_IWGRP), f"Write bit (GRP) present on {placed_path}"
        assert not (file_mode & stat.S_IWOTH), f"Write bit (OTH) present on {placed_path}"

        # Attempt in-place write in binary mode
        with pytest.raises(PermissionError):
            with open(placed_path, "wb") as f:
                f.write(b"TAMPERED_DATA")

        # Attempt in-place append mode
        with pytest.raises(PermissionError):
            with open(placed_path, "ab") as f:
                f.write(b"APPENDED_DATA")

        # Attempt in-place write with open in 'r+' mode
        with pytest.raises(PermissionError):
            with open(placed_path, "r+b") as f:
                f.write(b"OVERWRITE_DATA")

        # Attempt truncation via os.truncate
        with pytest.raises(PermissionError):
            os.truncate(str(placed_path), 0)

        # Confirm content was not modified
        assert placed_path.read_bytes() == payload_content

    def test_cas_blob_read_only_protection(self, tmp_path: Path):
        """CAS dedup blobs placed in blobs/ must be strictly read-only."""
        project = tmp_path / "cas_proj"
        src_file = tmp_path / "cas_data.bin"
        src_file.write_bytes(b"CAS_CONTENT_DEDUP_BLOB_999")

        rel_path, size, digest = place_managed_file(
            src_file, project, DataStage.RAW, "asset_cas", "ver_cas_1", register_blob=True
        )
        blob_file = blob_path(project, digest)
        assert blob_file.is_file()

        mode = blob_file.stat().st_mode
        assert not (mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

        with pytest.raises(PermissionError):
            with open(blob_file, "wb") as f:
                f.write(b"CORRUPTED_CAS_BLOB")

    def test_working_copy_isolation_never_mutates_original(self, tmp_path: Path):
        """Working copies must be writable separate copies (never hardlinks) whose mutations do not affect managed payload."""
        project = tmp_path / "work_proj"
        src = tmp_path / "source.txt"
        original_bytes = b"ORIGINAL_MANAGED_CONTENT_STAY_SAFE"
        src.write_bytes(original_bytes)

        rel_path, _, digest = place_managed_file(
            src, project, DataStage.RAW, "asset_work", "ver_orig_1"
        )
        managed_payload = tmp_path / rel_path

        # Create working copy
        working_file = create_working_copy(project, managed_payload, "ver_orig_1")
        assert working_file.is_file()
        assert working_file != managed_payload
        # Verify not a hardlink
        assert working_file.stat().st_ino != managed_payload.stat().st_ino

        # Mutating working copy must succeed
        with open(working_file, "wb") as f:
            f.write(b"MUTATED_WORKING_COPY_DATA_NEW")

        assert working_file.read_bytes() == b"MUTATED_WORKING_COPY_DATA_NEW"
        # Original managed payload MUST remain unaltered
        assert managed_payload.read_bytes() == original_bytes
        # Managed payload must still be read-only
        assert not (managed_payload.stat().st_mode & stat.S_IWUSR)

    def test_restored_payload_reapplies_read_only_mode(self, tmp_path: Path):
        """Trashing and then restoring a payload must re-apply 0o444 read-only mode bits."""
        project = tmp_path / "trash_proj"
        src = tmp_path / "to_trash.dat"
        src.write_bytes(b"TRASH_AND_RESTORE_ME")

        rel_path, _, _ = place_managed_file(
            src, project, DataStage.DERIVED, "asset_trash", "ver_t1"
        )
        placed = tmp_path / rel_path

        # Trash payload
        trashed_rel = trash_payload(project, placed, "ver_t1")
        trashed_path = tmp_path / trashed_rel
        assert not placed.exists()
        assert trashed_path.is_file()

        # Restore payload
        restored_rel = restore_payload(project, trashed_path, rel_path)
        restored_path = tmp_path / restored_rel
        assert restored_path.is_file()
        assert restored_path.read_bytes() == b"TRASH_AND_RESTORE_ME"

        # Check restored read-only bits
        assert not (restored_path.stat().st_mode & stat.S_IWUSR)
        with pytest.raises(PermissionError):
            with open(restored_path, "wb") as f:
                f.write(b"TAMPER_RESTORED")

    def test_restore_payload_conflict_raises_catalog_error(self, tmp_path: Path):
        """Restoring when the original target path is occupied must raise CatalogError and not overwrite."""
        project = tmp_path / "conflict_proj"
        src = tmp_path / "src.dat"
        src.write_bytes(b"INITIAL")
        rel_path, _, _ = place_managed_file(
            src, project, DataStage.RAW, "asset_c", "ver_c1"
        )
        placed = tmp_path / rel_path

        trashed_rel = trash_payload(project, placed, "ver_c1")
        trashed_path = tmp_path / trashed_rel

        # Re-create a file at the original target location
        placed.parent.mkdir(parents=True, exist_ok=True)
        placed.write_bytes(b"IMPOSTOR_FILE")

        with pytest.raises(CatalogError, match="already exists"):
            restore_payload(project, trashed_path, rel_path)

        assert placed.read_bytes() == b"IMPOSTOR_FILE"
        assert trashed_path.is_file()


# ===========================================================================
# Vector 2: Re-registration of identical version IDs (F19 Collision Prevention)
# ===========================================================================

class TestVersionCollisionAndImmutabilityEnforcement:
    """Stress tests verifying rejection of duplicate version IDs and rollback cleanliness."""

    def test_reregistration_same_version_id_differing_payload_raises(self, tmp_path: Path):
        """Attempting to re-register an existing version ID with different payload bytes must raise ImmutableVersionError."""
        project_dir = tmp_path / "proj_collision"
        project_dir.mkdir()
        service = DataCatalogService.open(project_dir)

        src_v1 = tmp_path / "v1.las"
        src_v1.write_bytes(b"PAYLOAD_VERSION_1_ORIGINAL")

        v1 = service.import_raw(src_v1)
        version_id = v1.id
        asset_id = v1.asset_id

        # Attempt to register DIFFERENT payload under SAME version_id
        src_v2 = tmp_path / "v2_fake.las"
        src_v2.write_bytes(b"PAYLOAD_VERSION_2_DIFFERING_CONTENT")

        with pytest.raises(ImmutableVersionError, match="already committed and immutable"):
            service.register_version(
                asset_id=asset_id,
                source_path=src_v2,
                stage=DataStage.RAW,
                version_id=version_id,
            )

        # Verify original version record and payload are intact
        reloaded_v1 = service.get_version(version_id)
        assert reloaded_v1.sha256 == hashlib.sha256(b"PAYLOAD_VERSION_1_ORIGINAL").hexdigest()
        assert (project_dir.parent / reloaded_v1.path).read_bytes() == b"PAYLOAD_VERSION_1_ORIGINAL"

    def test_reregistration_same_version_id_across_different_asset_raises(self, tmp_path: Path):
        """Attempting to register an existing version ID on a different asset must raise ImmutableVersionError."""
        project_dir = tmp_path / "proj_cross_asset"
        project_dir.mkdir()
        service = DataCatalogService.open(project_dir)

        src1 = tmp_path / "file1.dat"
        src1.write_bytes(b"DATA_1")
        v1 = service.import_raw(src1)

        src2 = tmp_path / "file2.dat"
        src2.write_bytes(b"DATA_2")
        v2 = service.import_raw(src2)

        src3 = tmp_path / "file3.dat"
        src3.write_bytes(b"DATA_3")

        with pytest.raises(ImmutableVersionError, match="already committed and immutable"):
            service.register_version(
                asset_id=v2.asset_id,
                source_path=src3,
                stage=DataStage.RAW,
                version_id=v1.id,
            )

    def test_reregistration_identical_payload_same_id_raises(self, tmp_path: Path):
        """Even with identical payload bytes, committing an existing version ID must raise ImmutableVersionError."""
        project_dir = tmp_path / "proj_identical"
        project_dir.mkdir()
        service = DataCatalogService.open(project_dir)

        src = tmp_path / "grid.dat"
        src.write_bytes(b"IDENTICAL_GRID_PAYLOAD")
        v1 = service.import_raw(src)

        with pytest.raises(ImmutableVersionError, match="already committed and immutable"):
            service.register_version(
                asset_id=v1.asset_id,
                source_path=src,
                stage=DataStage.DERIVED,
                version_id=v1.id,
            )

    def test_place_managed_file_collision_raises_file_exists_error(self, tmp_path: Path):
        """Low-level place_managed_file must raise FileExistsError if target payload exists."""
        project = tmp_path / "proj_storage_collision"
        src = tmp_path / "test.bin"
        src.write_bytes(b"BYTES_1")

        place_managed_file(src, project, DataStage.RAW, "asset_x", "ver_x")

        # Second placement with identical filename at same asset/version path
        src_2_dir = tmp_path / "other_dir"
        src_2_dir.mkdir()
        src_2 = src_2_dir / "test.bin"
        src_2.write_bytes(b"BYTES_2_DIFFERENT")

        with pytest.raises(FileExistsError, match="Managed payload already exists"):
            place_managed_file(src_2, project, DataStage.RAW, "asset_x", "ver_x")

    @pytest.mark.parametrize("malicious_id", [
        "../../escape",
        "/etc/passwd",
        "sub/dir/id",
        "ver\\backslash",
        "ver\x00null",
        "ver id with space",
        "",
        "   ",
    ])
    def test_malicious_path_traversal_version_ids_rejected(self, tmp_path: Path, malicious_id: str):
        """Unsafe or path traversal version IDs must be rejected before placing files."""
        project_dir = tmp_path / "proj_sec"
        project_dir.mkdir()
        service = DataCatalogService.open(project_dir)
        src = tmp_path / "safe.dat"
        src.write_bytes(b"SAFE_DATA")
        v1 = service.import_raw(src)

        src2 = tmp_path / "safe2.dat"
        src2.write_bytes(b"SAFE_DATA_2")

        with pytest.raises(CatalogError):
            service.register_version(
                asset_id=v1.asset_id,
                source_path=src2,
                stage=DataStage.RAW,
                version_id=malicious_id,
            )

    def test_collision_rollback_cleanliness(self, tmp_path: Path):
        """When version registration fails on collision, no stray files remain in temp or storage directories."""
        project_dir = tmp_path / "proj_rollback"
        project_dir.mkdir()
        service = DataCatalogService.open(project_dir)

        src1 = tmp_path / "src1.dat"
        src1.write_bytes(b"CONTENT_1")
        v1 = service.import_raw(src1)

        src2 = tmp_path / "src2.dat"
        src2.write_bytes(b"CONTENT_2")

        # Count files in project artifacts before failed attempt
        art_dir = project_dir.parent / f"{project_dir.name}.artifacts"
        files_before = set(art_dir.rglob("*"))

        with pytest.raises(ImmutableVersionError):
            service.register_version(
                asset_id=v1.asset_id,
                source_path=src2,
                stage=DataStage.RAW,
                version_id=v1.id,
            )

        # Verify no extra tmp or stray files left behind
        files_after = set(art_dir.rglob("*"))
        new_files = {f for f in (files_after - files_before) if f.is_file() and not f.name.startswith(".catalog.json")}
        assert len(new_files) == 0, f"Orphaned files after rollback: {new_files}"


# ===========================================================================
# Vector 3: Corrupting / Zeroing SQLite database (F20 Dual-Tier Self-Healing)
# ===========================================================================

class TestSqliteCorruptionAndSelfHealing:
    """Stress tests corrupting, zeroing, or truncating catalog.sqlite and verifying automatic recovery."""

    def test_mid_session_zero_byte_sqlite_recovers_via_sync(self, tmp_path: Path):
        """Zeroing out catalog.sqlite mid-session must be detected and fully healed by sync() / rebuild()."""
        doc = make_sample_document(catalog_revision=10)
        index = CatalogIndex(tmp_path)
        index.rebuild(doc)
        assert index.revision() == 10
        assert len(index.search_assets()) == 3

        # Zero out the SQLite database file
        index.close()
        index.db_path.write_bytes(b"")
        assert index.db_path.stat().st_size == 0

        # State check: revision must report None (unreadable/corrupt) and not fresh
        assert index.revision() is None
        assert index.is_fresh(doc) is False
        assert index.search_assets() == []

        # Calling sync() on doc must trigger full rebuild and self-heal
        synced = index.sync(doc)
        assert synced is True
        assert index.revision() == 10
        assert index.is_fresh(doc) is True

        # Verify full query fidelity restored
        assets = index.search_assets()
        assert {a["id"] for a in assets} == {"asset_alpha", "asset_beta", "asset_gamma"}
        assert len(index.list_versions("asset_beta")) == 1
        assert index.lineage_edges("ver_beta_1") == {
            "parents": ["ver_alpha_1"],
            "children": ["ver_gamma_1"],
        }
        assert index.assets_for_tag("Production") == ["asset_beta", "asset_gamma"]

    def test_mid_session_garbage_corruption_recovers_via_sync(self, tmp_path: Path):
        """Corrupting catalog.sqlite with random non-database bytes must be healed by sync()."""
        doc = make_sample_document(catalog_revision=15)
        index = CatalogIndex(tmp_path)
        index.rebuild(doc)

        # Overwrite with random garbage bytes
        index.close()
        index.db_path.write_bytes(b"CORRUPT_SQLITE_GARBAGE_HEADER_DATA_12345" * 50)

        # Queries must fail safely to default
        assert index.revision() is None
        assert index.is_fresh(doc) is False
        assert index.search_assets() == []
        assert index.lineage_edges("ver_beta_1") == {"parents": [], "children": []}

        # sync() self-heals
        assert index.sync(doc) is True
        assert index.revision() == 15
        assert {a["id"] for a in index.search_assets()} == {"asset_alpha", "asset_beta", "asset_gamma"}

    def test_corrupt_wal_and_shm_files_self_heals(self, tmp_path: Path):
        """Corrupting or dropping -wal and -shm files must be recovered via index reset/rebuild."""
        doc = make_sample_document(catalog_revision=20)
        index = CatalogIndex(tmp_path)
        index.rebuild(doc)

        # Write garbage to WAL and SHM
        wal_file = Path(f"{index.db_path}-wal")
        shm_file = Path(f"{index.db_path}-shm")
        wal_file.write_bytes(b"GARBAGE_WAL_CONTENT")
        shm_file.write_bytes(b"GARBAGE_SHM_CONTENT")

        index.close()
        index.reset()
        assert not wal_file.exists()
        assert not shm_file.exists()

        index.rebuild(doc)
        assert index.revision() == 20
        assert len(index.search_assets()) == 3

    def test_service_level_recovery_after_sqlite_deletion(self, tmp_path: Path):
        """DataCatalogService must self-heal index if SQLite database is deleted mid-session."""
        project_dir = tmp_path / "proj_heal"
        project_dir.mkdir()
        service = DataCatalogService.open(project_dir)

        src = tmp_path / "seis.sgy"
        src.write_bytes(b"SEISMIC_DATA_SAMPLE")
        v1 = service.import_raw(src)

        # Confirm SQLite index is present
        assert service._index.db_path.is_file()
        assert len(service._index.search_assets()) == 1

        # Delete the sqlite file directly from filesystem
        service._index.close()
        service._index.db_path.unlink()

        # Add another version through service: _sync_index_best_effort must restore the DB
        src2 = tmp_path / "seis_filt.sgy"
        src2.write_bytes(b"FILTERED_SEISMIC")
        service.import_raw(src2, asset_id=v1.asset_id)

        assert service._index.db_path.is_file()
        assert service._index.revision() == service.document.catalog_revision
        assert len(service._index.search_assets()) == 1
        assert len(service._index.list_versions(v1.asset_id)) == 2

    def test_dropped_table_recovered_by_rebuild_and_service_sync(self, tmp_path: Path):
        """If an individual table is dropped from catalog.sqlite, queries fail safely and service sync or rebuild heals it."""
        doc = make_sample_document(catalog_revision=5)
        index = CatalogIndex(tmp_path)
        index.rebuild(doc)

        # Drop the versions table
        conn = index.open()
        conn.execute("DROP TABLE versions")
        conn.commit()

        # Queries on missing table return safe defaults without throwing unhandled exceptions
        assert index.list_versions("asset_alpha") == []

        # Service-level sync or explicit rebuild heals the database
        index.reset()
        index.rebuild(doc)
        assert index.revision() == 5
        assert len(index.list_versions("asset_alpha")) == 1


# ===========================================================================
# Vector 4: Concurrent worker thread database queries during catalog sync
# ===========================================================================

class TestConcurrentQueriesDuringCatalogSync:
    """Stress tests verifying thread safety of CatalogIndex under heavy concurrent reader/writer workloads."""

    def test_concurrent_readers_during_rapid_rebuild_and_sync(self, tmp_path: Path):
        """Multiple worker threads query the index continuously while a writer rapidly rebuilds and syncs."""
        doc_base = make_sample_document(catalog_revision=1)
        index = CatalogIndex(tmp_path)
        index.rebuild(doc_base)

        num_reader_threads = 8
        duration_seconds = 2.0
        stop_event = threading.Event()
        query_counts = [0] * num_reader_threads
        reader_errors: list[tuple[int, Exception]] = []

        def reader_worker(worker_id: int):
            try:
                while not stop_event.is_set():
                    # Mix of different query types supported by CatalogIndex
                    index.search_assets(text="alpha")
                    index.search_assets(tag="QC Passed")
                    index.search_assets(stage=DataStage.RAW)
                    index.list_versions("asset_beta")
                    index.lineage_edges("ver_beta_1")
                    index.assets_for_tag("Production")
                    index.versions_for_tag("Production")
                    index.find_managed_raw("some_uri", "a" * 64)
                    query_counts[worker_id] += 1
            except Exception as exc:
                reader_errors.append((worker_id, exc))

        # Start readers
        threads = [
            threading.Thread(target=reader_worker, args=(i,), daemon=True)
            for i in range(num_reader_threads)
        ]
        for t in threads:
            t.start()

        # Writer loop: rapidly increment revisions and sync/rebuild
        writer_errors: list[Exception] = []
        sync_count = 0
        start_time = time.monotonic()
        try:
            while time.monotonic() - start_time < duration_seconds:
                sync_count += 1
                new_doc = make_sample_document(catalog_revision=sync_count + 1)
                # Alternate between sync() and occasional rebuild()
                if sync_count % 3 == 0:
                    index.rebuild(new_doc)
                else:
                    index.sync(new_doc)
                time.sleep(0.01)
        except Exception as exc:
            writer_errors.append(exc)
        finally:
            stop_event.set()
            for t in threads:
                t.join(timeout=5.0)

        # Assertions
        assert len(writer_errors) == 0, f"Writer thread failed: {writer_errors}"
        assert len(reader_errors) == 0, f"Reader threads encountered errors: {reader_errors}"
        assert sum(query_counts) > 50, f"Total queries executed ({sum(query_counts)}) was too low"
        assert sync_count >= 10, f"Total syncs ({sync_count}) was too low"

        # Final index consistency check
        final_doc = make_sample_document(catalog_revision=sync_count + 1)
        index.sync(final_doc)
        assert index.is_fresh(final_doc) is True
        assert len(index.search_assets()) == 3

    def test_concurrent_service_registrations_and_queries(self, tmp_path: Path):
        """DataCatalogService performs version registrations while reader threads concurrently query catalog index."""
        project_dir = tmp_path / "proj_concurrent_service"
        project_dir.mkdir()
        service = DataCatalogService.open(project_dir)

        src0 = tmp_path / "source_0.dat"
        src0.write_bytes(b"INITIAL_PAYLOAD_0")
        v0 = service.import_raw(src0)
        asset_id = v0.asset_id

        stop_event = threading.Event()
        reader_errors: list[Exception] = []
        read_iterations = [0]

        def reader_loop():
            try:
                while not stop_event.is_set():
                    # Query through service and direct index
                    service.list_versions(asset_id)
                    service.get_asset(asset_id)
                    service._index.search_assets()
                    service._index.list_versions(asset_id)
                    read_iterations[0] += 1
            except Exception as e:
                reader_errors.append(e)

        reader_thread = threading.Thread(target=reader_loop, daemon=True)
        reader_thread.start()

        # Register 25 versions in main thread
        try:
            for i in range(1, 26):
                src = tmp_path / f"source_{i}.dat"
                src.write_bytes(f"VERSION_DATA_PAYLOAD_{i}".encode("utf-8"))
                service.import_raw(
                    source_path=src,
                    asset_id=asset_id,
                )
        finally:
            stop_event.set()
            reader_thread.join(timeout=5.0)

        assert len(reader_errors) == 0, f"Reader thread failed during service registrations: {reader_errors}"
        assert read_iterations[0] > 10

        # Verify all 26 versions registered and indexed
        versions = service.list_versions(asset_id)
        assert len(versions) == 26
        indexed_versions = service._index.list_versions(asset_id)
        assert len(indexed_versions) == 26

    def test_concurrent_readers_during_mid_session_db_corruption(self, tmp_path: Path):
        """When SQLite is corrupted while reader threads are active, readers must not crash and recover after sync."""
        doc = make_sample_document(catalog_revision=50)
        index = CatalogIndex(tmp_path)
        index.rebuild(doc)

        stop_event = threading.Event()
        reader_crashes: list[Exception] = []

        def resilient_reader():
            try:
                while not stop_event.is_set():
                    # All these methods use _safe() wrapper
                    index.search_assets()
                    index.list_versions("asset_alpha")
                    index.lineage_edges("ver_alpha_1")
                    time.sleep(0.005)
            except Exception as exc:
                reader_crashes.append(exc)

        readers = [threading.Thread(target=resilient_reader, daemon=True) for _ in range(4)]
        for r in readers:
            r.start()

        try:
            time.sleep(0.05)
            # Corrupt the database file underneath active readers
            index.db_path.write_bytes(b"CORRUPTED_IN_FLIGHT_DATA")
            time.sleep(0.05)

            # Heal via sync
            index.sync(doc)
            time.sleep(0.05)
        finally:
            stop_event.set()
            for r in readers:
                r.join(timeout=5.0)

        assert len(reader_crashes) == 0, f"Readers crashed during underlying DB corruption: {reader_crashes}"
        assert index.revision() == 50
        assert len(index.search_assets()) == 3
