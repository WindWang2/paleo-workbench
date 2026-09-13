#!/usr/bin/env python
"""Measure full-file read/write/hash passes during managed RAW import funnels.

Run from the worktree root with the goal venv:

    .venv/bin/python docs/development/ingest-io-v12/measure_io.py

Counters (armed per scenario, after the catalog service is open):

- src_full_reads   opens of the SOURCE file in read-binary mode; every open in
                   these funnels streams the whole file, so opens == full passes
- payload_re_reads opens under <project>.artifacts/ (the re-read of the just
                   placed payload by blob registration shows up here)
- write_passes     tempfile.mkstemp calls under <project>.artifacts/ (one temp
                   file == one full byte-write target; rename/fsync excluded by
                   design, matching the goal's accounting)
- hash_passes      sha256_file() / _digest_of() invocations (the copy loop's
                   inline hash is not a function call; each copy adds exactly
                   one inline pass, visible via src_full_reads)

Scenarios:
  S1 service.import_raw(new content)                    — service funnel
  S2 lifecycle.register_resource_input (UI funnel, new content)
  S3 same content, new path, UI funnel                  — dedup hit
  S4 service.import_raw(known_sha256)                   — dedup hit, unverified
  S6 same path re-import, UI funnel                     — idempotence hit
  S5 import_folder wall time over a synthetic tree      — concurrency probe
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pathlib

PAYLOAD = b"seismic-trace-like-bytes" * 300_000  # ~7.6 MB


class Counters:
    def __init__(self, src: Path, artifacts_root: Path) -> None:
        self.src = src.resolve()
        self.root = artifacts_root.resolve()
        self.src_full_reads = 0
        self.payload_re_reads = 0
        self.write_passes = 0
        self.hash_passes = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "src_full_reads": self.src_full_reads,
            "payload_re_reads": self.payload_re_reads,
            "write_passes": self.write_passes,
            "hash_passes": self.hash_passes,
        }


def make_service(tmp: Path, name: str):
    from paleo_workbench.catalog.service import DataCatalogService

    project_path = tmp / name / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


def make_source(tmp: Path, name: str, payload: bytes | None = None) -> Path:
    src = tmp / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload if payload is not None else PAYLOAD)
    return src


def make_resource(src: Path):
    from paleo_workbench.project.models import ResourceItem

    return ResourceItem(
        name=src.name,
        path=src.resolve().as_posix(),
        type="seismic",
        format="sgy",
        checksum=None,
        external=False,
    )


def install_counters(counters: Counters):
    """Monkeypatch-style wrappers; returns an undo callable."""
    import paleo_workbench.catalog.checksum as checksum_mod
    import paleo_workbench.catalog.lifecycle as lifecycle_mod
    import paleo_workbench.catalog.adapter as adapter_mod
    import paleo_workbench.catalog.storage as storage_mod

    src = counters.src
    root = counters.root
    orig_open = pathlib.Path.open
    orig_mkstemp = tempfile.mkstemp
    orig_sha = checksum_mod.sha256_file
    orig_digest = storage_mod._digest_of
    orig_sha_lifecycle = lifecycle_mod.sha256_file_or_none
    orig_sha_adapter = adapter_mod.sha256_file_or_none

    def counting_open(self, mode="r", *args, **kwargs):
        try:
            resolved = Path(self).resolve()
        except OSError:
            resolved = self
        if "r" in mode and "b" in mode:
            if resolved == src:
                counters.src_full_reads += 1
            elif root in resolved.parents:
                counters.payload_re_reads += 1
        return orig_open(self, mode, *args, **kwargs)

    def counting_mkstemp(*args, **kwargs):
        directory = Path(kwargs.get("dir") or ".")
        try:
            resolved_dir = directory.resolve()
        except OSError:
            resolved_dir = directory
        under_root = root in resolved_dir.parents or resolved_dir == root
        # metadata/ holds the catalog manifest + SQLite store; their atomic
        # temp files are bookkeeping writes, not payload bytes — excluded to
        # match the goal's accounting (payload/blob writes only).
        metadata_dir = root / "metadata"
        under_metadata = (
            resolved_dir == metadata_dir or metadata_dir in resolved_dir.parents
        )
        if under_root and not under_metadata:
            counters.write_passes += 1
        return orig_mkstemp(*args, **kwargs)

    def counting_sha(path, *args, **kwargs):
        counters.hash_passes += 1
        return orig_sha(path, *args, **kwargs)

    def counting_digest(path):
        counters.hash_passes += 1
        return orig_digest(path)

    def counting_sha_or_none(path):
        # these wrap sha256_file; count at the leaf only (sha256_file itself)
        return orig_sha_lifecycle(path)

    pathlib.Path.open = counting_open
    tempfile.mkstemp = counting_mkstemp
    checksum_mod.sha256_file = counting_sha
    storage_mod._digest_of = counting_digest
    lifecycle_mod.sha256_file_or_none = counting_sha_or_none
    adapter_mod.sha256_file_or_none = counting_sha_or_none

    def undo():
        pathlib.Path.open = orig_open
        tempfile.mkstemp = orig_mkstemp
        checksum_mod.sha256_file = orig_sha
        storage_mod._digest_of = orig_digest
        lifecycle_mod.sha256_file_or_none = orig_sha_lifecycle
        adapter_mod.sha256_file_or_none = orig_sha_adapter

    return undo


def artifacts_root_of(service) -> Path:
    from paleo_workbench.catalog.storage import blob_dir_for

    return blob_dir_for(service.project_path).parent


def run_scenarios(tmp: Path) -> list[tuple[str, dict[str, int]]]:
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.lifecycle import register_resource_input

    results: list[tuple[str, dict[str, int]]] = []

    # S1 — service funnel, brand-new content (fresh project, empty blob store)
    svc = make_service(tmp, "s1")
    try:
        src = make_source(tmp, "s1.bin")
        c = Counters(src, artifacts_root_of(svc))
        undo = install_counters(c)
        try:
            svc.import_raw(src)
        finally:
            undo()
        results.append(("S1 service.import_raw(new)", c.snapshot()))
    finally:
        svc.close()

    # S2/S3/S4/S6 share one project so later scenarios can dedup/idempotence
    svc = make_service(tmp, "s2")
    try:
        root = artifacts_root_of(svc)

        src2 = make_source(tmp, "ui-first.bin")
        c = Counters(src2, root)
        undo = install_counters(c)
        try:
            register_resource_input(make_resource(src2), catalog=CoreCatalogAdapter(svc))
        finally:
            undo()
        results.append(("S2 UI funnel (new content)", c.snapshot()))

        src3 = make_source(tmp, "ui-second.bin")  # same bytes, new path
        c = Counters(src3, root)
        undo = install_counters(c)
        try:
            register_resource_input(make_resource(src3), catalog=CoreCatalogAdapter(svc))
        finally:
            undo()
        results.append(("S3 UI funnel (dedup hit)", c.snapshot()))

        src4 = make_source(tmp, "svc-dedup.bin")  # same bytes, new path
        import hashlib

        digest = hashlib.sha256(PAYLOAD).hexdigest()
        c = Counters(src4, root)
        undo = install_counters(c)
        try:
            svc.import_raw(src4, known_sha256=digest)
        finally:
            undo()
        results.append(("S4 service dedup (unverified)", c.snapshot()))

        c = Counters(src2, root)  # re-import the very same path
        undo = install_counters(c)
        try:
            register_resource_input(make_resource(src2), catalog=CoreCatalogAdapter(svc))
        finally:
            undo()
        results.append(("S6 UI funnel (idempotence hit)", c.snapshot()))
    finally:
        svc.close()

    return results


def run_folder_timing(tmp: Path) -> float:
    from paleo_workbench.resources.import_service import import_folder

    root = tmp / "treeroot"
    (root / "nested").mkdir(parents=True)
    for i in range(120):
        (root / f"w{i:03d}.las").write_text("~Version\n", encoding="utf-8")
        (root / "nested" / f"m{i:03d}.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    for i in range(30):
        (root / f"g{i:02d}.json").write_text('{"type": "FeatureCollection", "features": []}')
    (root / "empty.las").write_text("")
    (root / "._mac_junk.las").write_text("~Version\n", encoding="utf-8")

    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        report = import_folder(root, existing=[])
        best = min(best, time.perf_counter() - start)
    assert report.added_count == 120 + 120 + 30, report.added_count
    return best


def main() -> None:
    with TemporaryDirectory(prefix="io-measure-") as td:
        tmp = Path(td)
        rows = run_scenarios(tmp)
        wall = run_folder_timing(tmp)
    print(f"payload = {len(PAYLOAD) / 1e6:.1f} MB; folder = 153 files")
    print(f"{'scenario':<32} {'src_reads':>9} {'payload_rereads':>15} "
          f"{'writes':>7} {'hashes':>7}")
    for name, snap in rows:
        print(f"{name:<32} {snap['src_full_reads']:>9} "
              f"{snap['payload_re_reads']:>15} {snap['write_passes']:>7} "
              f"{snap['hash_passes']:>7}")
    print(f"import_folder best-of-3 wall time: {wall * 1000:.1f} ms")


if __name__ == "__main__":
    main()
