"""Regression nails for the ingest I/O pipeline (V12-A).

Pins the byte-level I/O shape of the managed RAW import funnels:

- new content: one pre-hash + one verified copy pass over the source, the
  blob written from the same read (zero re-reads of the just-placed payload)
- dedup hit through the UI funnel: exactly one full hash pass
- dedup hit with a digest of unknown provenance: the content re-proof stays
  (``test_same_size_different_content_never_adopts_existing_blob`` contract)
- folder import: parallel collection stays byte-identical to serial order

The negative-control test injects a deliberate double-hash regression and
asserts the counters see it, proving the ``== 1`` assertions above are not
vacuous.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest

import paleo_workbench.catalog.checksum as checksum_mod
import paleo_workbench.catalog.lifecycle as lifecycle_mod
import paleo_workbench.catalog.storage as storage_mod
from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.lifecycle import register_resource_input
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import blob_dir_for
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.import_service import import_folder

PAYLOAD = b"ingest-io-v12 trace bytes" * 40_000  # ~1 MB


class IOCounters:
    """Counts full-file read/write passes scoped to one import scenario."""

    def __init__(self, monkeypatch, src: Path, artifacts_root: Path) -> None:
        import tempfile

        self.src = src.resolve()
        self.root = artifacts_root.resolve()
        self.src_full_reads = 0
        self.payload_re_reads = 0
        self.write_passes = 0
        self.hash_fn_calls = 0  # sha256_file() + _digest_of() invocations
        self.digest_of_calls = 0

        orig_open = Path.open
        orig_mkstemp = tempfile.mkstemp
        orig_sha = checksum_mod.sha256_file
        orig_digest = storage_mod._digest_of
        src, root = self.src, self.root

        def counting_open(path, mode="r", *args, **kwargs):
            try:
                resolved = Path(path).resolve()
            except OSError:
                resolved = Path(path)
            if "r" in mode and "b" in mode:
                if resolved == src:
                    self.src_full_reads += 1
                elif root in resolved.parents:
                    self.payload_re_reads += 1
            return orig_open(path, mode, *args, **kwargs)

        def counting_mkstemp(*args, **kwargs):
            directory = Path(kwargs.get("dir") or ".")
            try:
                resolved_dir = directory.resolve()
            except OSError:
                resolved_dir = directory
            metadata_dir = root / "metadata"
            bookkeeping = (
                resolved_dir == metadata_dir
                or metadata_dir in resolved_dir.parents
            )
            if (root in resolved_dir.parents) and not bookkeeping:
                self.write_passes += 1
            return orig_mkstemp(*args, **kwargs)

        def counting_sha(path, *args, **kwargs):
            self.hash_fn_calls += 1
            return orig_sha(path, *args, **kwargs)

        def counting_digest(path):
            self.hash_fn_calls += 1
            self.digest_of_calls += 1
            return orig_digest(path)

        monkeypatch.setattr(Path, "open", counting_open)
        monkeypatch.setattr(tempfile, "mkstemp", counting_mkstemp)
        monkeypatch.setattr(checksum_mod, "sha256_file", counting_sha)
        monkeypatch.setattr(storage_mod, "_digest_of", counting_digest)


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _source(tmp_path: Path, name: str) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(PAYLOAD)
    return src


def _resource(src: Path, *, checksum: str | None = None) -> ResourceItem:
    return ResourceItem(
        name=src.name,
        path=src.resolve().as_posix(),
        type="seismic",
        format="sgy",
        checksum=checksum,
        external=False,
    )


def _artifacts_root(service: DataCatalogService) -> Path:
    return blob_dir_for(service.project_path).parent


def _register(service: DataCatalogService, src: Path, *, checksum=None):
    return register_resource_input(
        _resource(src, checksum=checksum), catalog=CoreCatalogAdapter(service)
    )


# ------------------------------------------------------------- I/O shape


def test_ui_import_new_content_reads_source_twice_and_never_rereads_payload(
    service, tmp_path, monkeypatch
):
    """New content via the UI funnel: pre-hash + verified copy = 2 source
    passes; the blob is written from the same read (no payload re-read)."""
    src = _source(tmp_path, "first.bin")
    counters = IOCounters(monkeypatch, src, _artifacts_root(service))
    _register(service, src)
    assert counters.src_full_reads == 2
    assert counters.payload_re_reads == 0
    assert counters.write_passes == 2  # payload temp + blob temp, nothing else
    version = service.document.versions[0]
    assert "blobs" not in version.path  # first import keeps its stage payload
    assert Path(service.resolve_path(version)).read_bytes() == PAYLOAD


def test_ui_import_dedup_hit_hashes_source_exactly_once(
    service, tmp_path, monkeypatch
):
    """Dedup hit via the UI funnel: the fresh in-process pre-hash is also the
    content proof — exactly one full pass, no copy, no re-proof."""
    _register(service, _source(tmp_path, "seed.bin"))
    second = _source(tmp_path, "twin.bin")  # same bytes, new path
    counters = IOCounters(monkeypatch, second, _artifacts_root(service))
    _register(service, second)
    assert counters.src_full_reads == 1
    assert counters.digest_of_calls == 0  # trusted fresh digest, no re-proof
    assert counters.write_passes == 0
    version = service.document.versions[-1]
    assert "/blobs/" in version.path  # still shares the blob, O(1), copy-free


def test_unverified_digest_dedup_hit_still_reproves_content(
    service, tmp_path, monkeypatch
):
    """A digest of unknown provenance (e.g. recorded at scan time) must keep
    the content re-proof on the dedup fast path — the honest-checksum
    contract pinned by test_same_size_different_content_..._blob."""
    _register(service, _source(tmp_path, "seed.bin"))
    scan_seen = _source(tmp_path, "scan-twin.bin")  # same bytes, new path
    stale_style_checksum = hashlib.sha256(PAYLOAD).hexdigest()
    counters = IOCounters(monkeypatch, scan_seen, _artifacts_root(service))
    _register(service, scan_seen, checksum=stale_style_checksum)
    assert counters.src_full_reads == 1  # exactly the re-proof pass
    assert counters.digest_of_calls == 1
    assert counters.write_passes == 0


def test_service_import_without_known_checksum_streams_once(
    service, tmp_path, monkeypatch
):
    """service.import_raw(src) with no digest: single copy pass, blob written
    from the same stream — the just-placed payload is never re-read."""
    src = _source(tmp_path, "plain.bin")
    counters = IOCounters(monkeypatch, src, _artifacts_root(service))
    service.import_raw(src)
    assert counters.src_full_reads == 1
    assert counters.payload_re_reads == 0
    assert counters.write_passes == 2


# ------------------------------------------------------- negative control


def test_io_counters_detect_double_hashing_regression(
    service, tmp_path, monkeypatch
):
    """Negative control for the ``== 1`` assertion above: inject the classic
    regression (the funnel's pre-hash runs twice) and the counters MUST see
    2 passes — i.e. the main assertions have teeth and are not vacuous."""
    _register(service, _source(tmp_path, "seed.bin"))
    second = _source(tmp_path, "twin.bin")

    real_hash = lifecycle_mod.sha256_file_or_none

    def double_hash(path):
        real_hash(path)  # the wasted pass a regression would re-add
        return real_hash(path)

    monkeypatch.setattr(lifecycle_mod, "sha256_file_or_none", double_hash)
    counters = IOCounters(monkeypatch, second, _artifacts_root(service))
    _register(service, second)
    assert counters.src_full_reads == 2  # detector fires: 2 != 1 pinned above


# ------------------------------------------------- folder determinism


def _make_tree(root: Path) -> None:
    (root / "nested").mkdir(parents=True)
    for i in range(40):
        (root / f"w{i:03d}.las").write_text("~Version\n", encoding="utf-8")
        (root / "nested" / f"m{i:03d}.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (root / "empty.las").write_text("", encoding="utf-8")
    (root / "._mac_junk.las").write_text("~Version\n", encoding="utf-8")


def test_import_folder_results_are_order_identical_with_parallel_collection(
    tmp_path, monkeypatch
):
    """Parallel collection must be byte-identical to the serial order:
    same added items (same order), same warnings, same filtered paths."""
    root = tmp_path / "tree"
    _make_tree(root)
    baseline = import_folder(root, existing=[])

    import paleo_workbench.resources.import_service as import_service

    real_collect = import_service._collect_resource

    def jittery_collect(path, project_path=None, *, preferred_only=False):
        time.sleep(0.001 + (hash(path.name) % 7) * 0.001)
        return real_collect(path, project_path, preferred_only=preferred_only)

    monkeypatch.setattr(import_service, "_collect_resource", jittery_collect)
    shaken = import_folder(root, existing=[])

    assert [r.path for r in shaken.added] == [r.path for r in baseline.added]
    assert shaken.warnings == baseline.warnings
    assert shaken.skipped_path == baseline.skipped_path
    assert shaken.skipped_filter == baseline.skipped_filter
    # And the order is the sorted-rglob order, not completion order.
    expected = sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith("._") and p.stat().st_size > 0
    )
    assert [Path(r.path).name for r in shaken.added] == [p.name for p in expected]


def test_import_folder_collection_actually_runs_in_parallel(
    tmp_path, monkeypatch
):
    """The metadata collection must use more than one worker thread: the
    first two files rendezvous on a barrier only passable concurrently."""
    root = tmp_path / "tree"
    _make_tree(root)

    import paleo_workbench.resources.import_service as import_service

    real_collect = import_service._collect_resource
    barrier = threading.Barrier(2, timeout=10)
    seen_threads: set[int] = set()
    lock = threading.Lock()

    def rendezvous_collect(path, project_path=None, *, preferred_only=False):
        with lock:
            seen_threads.add(threading.get_ident())
        barrier.wait()
        return real_collect(path, project_path, preferred_only=preferred_only)

    monkeypatch.setattr(import_service, "_collect_resource", rendezvous_collect)
    report = import_folder(root, existing=[])
    assert report.added_count == 80
    assert len(seen_threads) >= 2  # at least two distinct worker threads
