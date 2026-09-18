#!/usr/bin/env python3
"""Freeze GC / dedup / paged-query oracles for data.catalog_gc (conv-15).

Runs the REAL Python catalog stack (DataCatalogService + catalog.gc +
catalog.dedup + the paged query surface) over deterministic scenario trees,
then freezes the resulting reports / rows / error texts into
``tests/cpp/data/fixtures/catalog_gc/<scenario>/oracle.json`` next to the
project tree itself (``tree/``). The C++ test copies ``tree/`` into a temp
root, loads the very same catalog.sqlite through CatalogRepository and must
reproduce every frozen value. Absolute paths are recorded with a ``<ROOT>``
placeholder (the scenario root) so the C++ side can substitute its own.

Every expectation is derived from real module output — no hand-written
expected values. Re-running this script regenerates the fixtures (ids and
timestamps are frozen as-generated; the C++ side consumes them verbatim).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from paleo_workbench.catalog import dedup, gc
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import place_managed_file
from paleo_workbench.catalog.models import DataStage

REPO = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO / "tests" / "cpp" / "data" / "fixtures" / "catalog_gc"

FRESH_HEARTBEAT = "9999-12-31T23:59:59"   #永远新鲜：任何现实 now 都小于它
DEAD_HEARTBEAT = "2000-01-01T00:00:00"    #永远过期：任何现实 now-1h 都大于它


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _rel(root: Path, path: Path | str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    return Path(p).relative_to(root).as_posix()


def _norm(root: Path, text: str) -> str:
    return text.replace(str(root), "<ROOT>")


def _report_items(root: Path, report: gc.GcReport) -> list[dict]:
    out = [
        {"kind": item.kind, "rel": _rel(root, item.path), "size": item.size}
        for item in report.items
    ]
    return sorted(out, key=lambda r: (r["kind"], r["rel"]))


def _tree_files(root: Path) -> list[str]:
    """Files under *root*, excluding store bookkeeping: the canonical
    metadata dir (sqlite + WAL/SHM + manifest checkpoints written by Python's
    close()) and the durable telemetry log (``<stem>.artifacts/catalog/``) —
    neither is a GC subject, and the C++ replay implements no manifest/telemetry
    writer. The C++ comparator applies the same rule."""
    excluded = root / "demo.artifacts" / "metadata"
    excluded_telemetry = root / "demo.artifacts" / "catalog"
    return sorted(
        _rel(root, p)
        for p in root.rglob("*")
        if p.is_file()
        and excluded not in p.resolve().parents
        and excluded_telemetry not in p.resolve().parents
    )


def _open(project_file: Path) -> DataCatalogService:
    # sweep_temp=False keeps the tree exactly as built: the sweeps under test
    # must see the fabricated orphans, not have the open path eat them.
    return DataCatalogService.open(project_file, sweep_temp=False)


def _checkpoint(sqlite_path: Path) -> None:
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _add_lease(sqlite_path: Path, lease_id: str, target: str, heartbeat: str) -> None:
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO staging_leases"
            " (lease_id, target, kind, acquired_at, heartbeat_at)"
            " VALUES (?,?,?,?,?)",
            (lease_id, target, "register", heartbeat, heartbeat),
        )
        conn.commit()
    finally:
        conn.close()


def _rel_from(rel: str) -> str:
    """place_managed_file already returns a project-dir-relative POSIX string."""
    return Path(rel).as_posix()


def _artifact_root(run_root: Path, name: str) -> Path:
    """The ``<stem>.artifacts/<name>`` directory of the demo project."""
    return run_root / "demo.artifacts" / name


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)


def _sweep_run(tree: Path, *, explicit: bool) -> dict:
    """plan+sweep on an independent copy; freeze removed + remaining files."""
    work = Path(tempfile.mkdtemp(prefix="pwb_gc_sweep_"))
    try:
        run_root = work / "run"
        _copy_tree(tree, run_root)
        service = _open(run_root / "demo.paleo.json")
        try:
            report = gc.sweep_gc(service, dry_run=False, explicit=explicit)
            removed = sorted(
                ({"kind": i.kind, "rel": _rel(run_root, i.path)} for i in report.items),
                key=lambda r: (r["kind"], r["rel"]),
            )
        finally:
            service.close()
        _checkpoint(run_root / "demo.artifacts" / "metadata" / "catalog.sqlite")
        return {"removed": removed, "remaining_files": _tree_files(run_root)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _cleanup_run(tree: Path) -> dict:
    work = Path(tempfile.mkdtemp(prefix="pwb_gc_clean_"))
    try:
        run_root = work / "run"
        _copy_tree(tree, run_root)
        service = _open(run_root / "demo.paleo.json")
        try:
            report = gc.cleanup_working_copies(service)
            removed = sorted(
                ({"kind": i.kind, "rel": _rel(run_root, i.path)} for i in report.items),
                key=lambda r: (r["kind"], r["rel"]),
            )
        finally:
            service.close()
        _checkpoint(run_root / "demo.artifacts" / "metadata" / "catalog.sqlite")
        return {"removed": removed, "remaining_files": _tree_files(run_root)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- scenarios


def scenario_gc_orphans() -> None:
    scenario = OUT_ROOT / "gc_orphans"
    tree = scenario / "tree"
    shutil.rmtree(scenario, ignore_errors=True)
    tree.mkdir(parents=True)
    root = tree.resolve()
    incoming = tree / "incoming"
    incoming.mkdir()

    def source(name: str, payload: bytes) -> Path:
        p = incoming / name
        p.write_bytes(payload)
        return p

    project = root / "demo.paleo.json"
    project.write_text("{}", encoding="utf-8")

    service = _open(project)
    v1 = service.import_raw(source("a.bin", b"payload-a"))
    # A referenced payload whose NAME matches the temp pattern must survive
    # every sweep (gc.py step-4 referenced guard, #889).
    vtmp = service.import_raw(source("well_data.tmp", b"keep temp-named"))
    live_working = service.create_working_copy(v1.id)
    service.close()
    _checkpoint(root / "demo.artifacts" / "metadata" / "catalog.sqlite")

    # Fabricate one orphan of every class (plus lease guards).
    (root / "demo.artifacts" / "raw" / "ghost_asset" / "ghost_version").mkdir(
        parents=True
    )
    leased_stage_orphan = (
        root / "demo.artifacts" / "raw" / "ghost_asset" / "ghost_version"
        / "leftover.bin"
    )
    leased_stage_orphan.write_bytes(b"orphan-guarded-by-lease")
    (root / "demo.artifacts" / "outputs" / "ghost2").mkdir(parents=True)
    (root / "demo.artifacts" / "outputs" / "ghost2" / "leftover2.bin").write_bytes(
        b"orphan2"
    )
    (root / "demo.artifacts" / "working" / "ver_ghost").mkdir(parents=True)
    (root / "demo.artifacts" / "working" / "ver_ghost" / "wip.txt").write_bytes(
        b"abandoned"
    )
    (root / "demo.artifacts" / "trash" / "ver_ghost2").mkdir(parents=True)
    (root / "demo.artifacts" / "trash" / "ver_ghost2" / "payload.bin").write_bytes(
        b"trash-orphan"
    )
    (root / "demo.artifacts" / "raw" / ".place-abc123").write_bytes(b"stale")
    (root / "demo.artifacts" / "intermediate" / ".blob-notes").write_bytes(b"stale")
    (root / "demo.artifacts" / "metadata" / ".catalog.json.zzz.tmp").write_bytes(
        b"stale"
    )
    (root / "demo.artifacts" / "outputs" / "junk.tmp").write_bytes(b"stale")
    (root / "demo.artifacts" / "derived" / "empty_a" / "empty_b").mkdir(parents=True)
    junk_digest = dedup.place_blob(
        project, source("junk.bin", b"unreferenced blob bytes")
    )[1]

    db_path = root / "demo.artifacts" / "metadata" / "catalog.sqlite"
    _add_lease(db_path, "lease_fresh", "demo.artifacts/raw/ghost_asset", FRESH_HEARTBEAT)
    _add_lease(db_path, "lease_dead", "demo.artifacts/raw/dead_target", DEAD_HEARTBEAT)

    service = _open(project)
    try:
        plan_explicit = _report_items(root, gc.plan_gc(service, explicit=True))
        plan_auto = _report_items(root, gc.plan_gc(service, explicit=False))
    finally:
        service.close()
    sweep_auto = _sweep_run(tree, explicit=False)
    sweep_explicit = _sweep_run(tree, explicit=True)
    cleanup = _cleanup_run(tree)

    oracle = {
        "scenario": "gc_orphans",
        "plan_explicit": plan_explicit,
        "plan_auto": plan_auto,
        "sweep_auto": sweep_auto,
        "sweep_explicit": sweep_explicit,
        "cleanup_working_copies": cleanup,
        # Git tracks files, not directories: an empty fixture directory does
        # not survive a fresh clone. The consumer materializes these after
        # copying the tree (decisions D16).
        "fabricated_empty_dirs": [
            "demo.artifacts/derived/empty_a/empty_b",
        ],
        "meta": {
            "junk_digest": junk_digest,
            "referenced_temp_payload": _rel(root, vtmp.path),
            "live_working_rel": _rel(root, live_working),
            "leased_stage_orphan": _rel(root, leased_stage_orphan),
        },
    }
    _write_oracle(scenario, oracle)


def scenario_dedup_flow() -> None:
    scenario = OUT_ROOT / "dedup_flow"
    tree = scenario / "tree"
    shutil.rmtree(scenario, ignore_errors=True)
    tree.mkdir(parents=True)
    root = tree.resolve()
    incoming = tree / "incoming"
    incoming.mkdir()

    payload_p = b"shared dataset bytes" * 40
    payload_q = b"other content Q" * 55
    digest_p = _sha(payload_p)
    digest_q = _sha(payload_q)

    project = tree / "demo.paleo.json"
    project.write_text("{}", encoding="utf-8")
    (incoming / "one.bin").write_bytes(payload_p)
    (incoming / "two.bin").write_bytes(payload_p)
    (incoming / "three.bin").write_bytes(payload_q)
    (incoming / "junk.bin").write_bytes(b"junk unreferenced")

    service = _open(project)
    try:
        v1 = service.import_raw(incoming / "one.bin")
        v2 = service.import_raw(incoming / "two.bin", known_sha256=digest_p)
        v3 = service.import_raw(incoming / "three.bin")
        digest_junk = dedup.place_blob(project, incoming / "junk.bin")[1]
        metrics_before = dedup.blob_metrics(project, service.document)
        plan_before = sorted(dedup.plan_blob_gc(project, service.document))

        v2_path_before = v2.path
        service.trash_version(v2.id, reason="dedup test")
        v2_path_after_trash = service.get_version(v2.id).path
        service.restore_version(v2.id)
        v2_path_after_restore = service.get_version(v2.id).path
        blob_of_v2_still_there = dedup.has_blob(project, digest_p)

        service.trash_version(v3.id, reason="purge me")
        purge_removed = service.purge_trashed()
        metrics_after = dedup.blob_metrics(project, service.document)
        plan_after = sorted(dedup.plan_blob_gc(project, service.document))
        blob_report_after = dedup.blob_report(project, service.document)

        versions = [
            {
                "id": v.id,
                "asset_id": v.asset_id,
                "path": _rel(root, v.path) if not Path(v.path).is_absolute() else v.path,
                "size_bytes": v.size_bytes,
                "sha256": v.sha256,
                "trashed": v.trashed,
            }
            for v in (service.get_version(v1.id), service.get_version(v2.id))
        ]
        versions.sort(key=lambda r: r["id"])
    finally:
        service.close()
    _checkpoint(root / "demo.artifacts" / "metadata" / "catalog.sqlite")

    # The sweep helper reopens the copied project by file path.
    sweep = _dedup_sweep_run(tree, [digest_q, digest_junk])
    oracle = {
        "scenario": "dedup_flow",
        "digest_p": digest_p,
        "digest_q": digest_q,
        "digest_junk": digest_junk,
        "v2_is_blob_backed": "/blobs/" in v2_path_before,
        "v2_path_before": _rel(root, v2_path_before),
        "v2_path_after_trash": _rel(root, v2_path_after_trash),
        "v2_path_after_restore": _rel(root, v2_path_after_restore),
        "blob_of_v2_still_there": blob_of_v2_still_there,
        "purge_removed": purge_removed,
        "versions": versions,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "plan_before": plan_before,
        "plan_after": plan_after,
        "blob_report_after": blob_report_after,
        "sweep": sweep,
    }
    _write_oracle(scenario, oracle)


def _dedup_sweep_run(tree: Path, digests: list[str]) -> dict:
    work = Path(tempfile.mkdtemp(prefix="pwb_dedup_sweep_"))
    try:
        run_root = work / "run"
        _copy_tree(tree, run_root)
        project = run_root / "demo.paleo.json"
        service = _open(project)
        document = service.document
        removed = sorted(dedup.sweep_unreferenced_blobs(project, document))
        service.close()
        blobs = sorted(
            _rel(run_root, p)
            for p in _artifact_root(run_root, "blobs").rglob("*")
            if p.is_file()
        )
        missing = [d for d in digests if not dedup.has_blob(project, d)]
        return {"removed": removed, "remaining_blobs": blobs, "removed_have_been": missing}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def scenario_place_rules() -> None:
    """place_managed_file rules. Every case runs on a FRESH copy of a pristine
    skeleton tree so the committed fixture stays replayable (a case that
    already placed its target would make the C++ replay hit FileExistsError).
    """
    scenario = OUT_ROOT / "place_rules"
    shutil.rmtree(scenario, ignore_errors=True)
    tree = scenario / "tree"
    tree.mkdir(parents=True)
    incoming = tree / "incoming"
    incoming.mkdir()
    (tree / "demo.paleo.json").write_text("{}", encoding="utf-8")

    content_b = b"dedup-adopt-content-B" * 30
    digest_b = _sha(content_b)
    (incoming / "seed_b.bin").write_bytes(content_b)
    (incoming / "seed_b2.bin").write_bytes(content_b)
    (incoming / "one.bin").write_bytes(b"one")
    (incoming / "move_me.bin").write_bytes(b"move-payload" * 20)
    (incoming / "mm.bin").write_bytes(b"real content")
    (incoming / "sized.bin").write_bytes(b"S" * 40)
    (incoming / "twin.bin").write_bytes(b"T" * 40)
    (incoming / "dup.bin").write_bytes(b"dup")

    digest_sized = _sha(b"S" * 40)

    def run(tag: str, body) -> dict:
        work = Path(tempfile.mkdtemp(prefix="pwb_place_"))
        try:
            run_root = work / "run"
            _copy_tree(tree, run_root)
            project = run_root / "demo.paleo.json"
            result = body(project, run_root / "incoming")
            if "error" in result and result["error"] is not None:
                result["error"] = _norm(run_root, result["error"])
            result["case"] = tag
            return result
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def placed(result, rel, size, sha):
        return {"rel_path": rel, "size_bytes": size, "sha256": sha, **result}

    cases = {}
    cases["ok_new"] = run("ok_new", lambda project, inc: (
        lambda r: placed({}, r[0], r[1], r[2]))(
        place_managed_file(inc / "one.bin", project, DataStage.RAW,
                           "asset_p1", "ver_p1")))

    def case_dedup_adopt(project, inc):
        dedup.place_blob(project, inc / "seed_b.bin", digest_b)
        rel, size, sha = place_managed_file(
            inc / "seed_b2.bin", project, DataStage.DERIVED, "asset_p2",
            "ver_p2", known_sha256=digest_b)
        return placed({"source_removed": False}, _rel_from(rel),
                      size, sha)
    cases["dedup_adopt"] = run("dedup_adopt", case_dedup_adopt)

    def case_dedup_move(project, inc):
        rel, size, sha = place_managed_file(
            inc / "move_me.bin", project, DataStage.OUTPUT, "asset_p3",
            "ver_p3", keep_source=False, register_blob=True)
        return placed({"source_removed": not (inc / "move_me.bin").exists(),
                       "rel_prefix": "demo.artifacts/outputs/asset_p3/ver_p3/",
                       "blob_placed": dedup.has_blob(project, sha)},
                      _rel_from(rel), size, sha)
    cases["dedup_move"] = run("dedup_move", case_dedup_move)

    def case_err_mismatch(project, inc):
        try:
            place_managed_file(inc / "mm.bin", project, DataStage.RAW,
                               "asset_pe", "ver_mismatch",
                               known_sha256="0" * 64)
            return {"error": None}
        except Exception as exc:  # noqa: BLE001 - freeze the real error text
            return {"error": str(exc)}
    cases["err_mismatch"] = run("err_mismatch", case_err_mismatch)

    def case_err_same_size(project, inc):
        dedup.place_blob(project, inc / "sized.bin", digest_sized)
        try:
            place_managed_file(inc / "twin.bin", project, DataStage.RAW,
                               "asset_pe", "ver_same_size",
                               known_sha256=digest_sized)
            return {"error": None}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
    cases["err_same_size_diff_content"] = run("err_same_size", case_err_same_size)

    def case_err_exists(project, inc):
        place_managed_file(inc / "dup.bin", project, DataStage.RAW,
                           "asset_p5", "ver_p5")
        try:
            place_managed_file(inc / "dup.bin", project, DataStage.RAW,
                               "asset_p5", "ver_p5")
            return {"error": None}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
    cases["err_exists"] = run("err_exists", case_err_exists)

    def case_unsafe(project, inc, field, value):
        kwargs = {f"{field}_id": value}
        try:
            place_managed_file(inc / "dup.bin", project, DataStage.RAW,
                               kwargs.get("asset_id", "asset_px"),
                               kwargs.get("version_id", "ver_px"))
            return {"error": None}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
    cases["err_unsafe_asset"] = run("err_unsafe_asset",
                                    lambda p, i: case_unsafe(p, i, "asset", "../evil"))
    cases["err_unsafe_asset_dot"] = run("err_unsafe_asset_dot",
                                        lambda p, i: case_unsafe(p, i, "asset", ".hidden"))
    cases["err_unsafe_version"] = run("err_unsafe_version",
                                      lambda p, i: case_unsafe(p, i, "version", "a/b"))
    # repr() quote-switch: an id containing a single quote is rendered with
    # double quotes in the Python error text.
    cases["err_unsafe_asset_quote"] = run(
        "err_unsafe_asset_quote",
        lambda p, i: case_unsafe(p, i, "asset", "ev'il"))
    # Unicode alnum ids are SAFE in Python (str.isalnum) and reach placement;
    # the C++ gate accepts them as a declared superset (decisions D14).
    cases["ok_unicode_asset_id"] = run(
        "ok_unicode_asset_id",
        lambda project, inc: (
            lambda r: placed({}, r[0], r[1], r[2]))(
            place_managed_file(inc / "one.bin", project, DataStage.RAW,
                               "asset_资产1", "ver_utf8")))

    oracle = {
        "scenario": "place_rules",
        "digest_b": digest_b,
        "digest_sized": digest_sized,
        "cases": cases,
    }
    _write_oracle(scenario, oracle)


# ------------------------------------------------------------- paged queries


def _row_freeze(root: Path, row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if key == "metadata":
            try:
                out[key] = json.loads(value) if value else {}
            except (TypeError, ValueError):
                out[key] = {}
        else:
            out[key] = value
    return out


def scenario_paged_queries() -> None:
    scenario = OUT_ROOT / "paged_queries"
    tree = scenario / "tree"
    shutil.rmtree(scenario, ignore_errors=True)
    tree.mkdir(parents=True)
    root = tree.resolve()
    incoming = tree / "incoming"
    incoming.mkdir()
    (tree / "demo.paleo.json").write_text("{}", encoding="utf-8")

    service = _open(tree / "demo.paleo.json")
    try:
        made = {}
        for i in range(8):
            src = incoming / f"incoming_{i:03d}.las"
            src.write_text("c" * (12 + i * 7), encoding="utf-8")
            made[f"well_{i:03d}"] = service.import_raw(
                src, name=f"well_{i:03d}"
            )
        # A second (DERIVED) version on well_001: exercises stage/version
        # order and the current-version join columns.
        derived_src = incoming / "derived_grid.npz"
        derived_src.write_bytes(b"derived-grid-bytes")
        service.register_version(
            made["well_001"].asset_id, derived_src, DataStage.DERIVED,
            parent_version_ids=[made["well_001"].id],
        )
        # CJK + mixed-case name for the bounded text-fold envelope.
        cjk_src = incoming / "gulf.las"
        cjk_src.write_bytes(b"gulf-bytes")
        service.import_raw(cjk_src, name="Well_008-Gulf 相带")
        # Tags (normalized on write): one plain, one with case+space to pin
        # the query-side normalization.
        service.add_tag("qc_ok", asset_id=made["well_003"].asset_id)
        service.add_tag("Batch A", asset_id=made["well_004"].asset_id)
        service.trash_asset(made["well_006"].asset_id)
        # A LIVE version with size_bytes NULL: the per-column NULLS-first key
        # must lead it in the size order (the Python fallback keys on the row
        # value, not on version presence — review finding, conv-15 R2).
        from paleo_workbench.catalog.db import DirtySet
        live = service.get_asset(made["well_005"].asset_id)
        live_version = service.get_version(live.current_version_id)
        live_version.size_bytes = None
        service._save(DirtySet(versions={live_version.id: None}))
    finally:
        service.close()
    _checkpoint(root / "demo.artifacts" / "metadata" / "catalog.sqlite")

    service = _open(tree / "demo.paleo.json")
    queries: list[dict] = []

    def run(name: str, **query) -> None:
        rows = service.search_assets_page(**query)
        count = service.count_assets(
            text=query.get("text"),
            stage=query.get("stage"),
            tags=query.get("tags"),
            tag_op=query.get("tag_op", "and"),
            type=query.get("type"),
            asset_id=query.get("asset_id"),
            asset_ids=query.get("asset_ids"),
            include_trashed=bool(query.get("include_trashed", False)),
            trashed_only=bool(query.get("trashed_only", False)),
        )
        queries.append({
            "name": name,
            "query": {k: v for k, v in query.items() if v is not None},
            "rows": [_row_freeze(root, row) for row in rows],
            "count": count,
        })

    try:
        page0 = service.search_assets_page(limit=5, order_by="name")
        run("page0_name_limit5", limit=5, order_by="name")
        run("page1_name_offset5", limit=5, offset=5, order_by="name")
        run("keyset_after_page0", limit=5, order_by="name",
            after=(page0[-1]["name"], page0[-1]["id"]))
        run("order_name_desc", limit=100, order_by="name_desc")
        run("order_type", limit=100, order_by="type")
        run("order_modified", limit=100, order_by="modified")
        run("order_stage", limit=100, order_by="stage")
        run("order_size", limit=100, order_by="size")
        run("order_version", limit=100, order_by="version")
        run("order_unknown_falls_back_name", limit=100, order_by="bogus")
        run("text_well_00", limit=100, text="well_00")
        # Whitespace is verbatim in the search fold: a needle with a leading
        # space matches nothing (review finding, conv-15 R2).
        run("text_whitespace_verbatim", limit=100, text=" well_000")
        run("text_case_fold", limit=100, text="WELL_008-GULF")
        run("text_cjk", limit=100, text="相带")
        run("text_miss", limit=100, text="no-such-needle")
        run("tags_qc_and", limit=100, tags=["qc_ok"])
        run("tags_qc_and_normalized", limit=100, tags=["QC_OK"])
        run("tags_or", limit=100, tags=["qc_ok", "Batch A"], tag_op="or")
        run("tags_or_normalized", limit=100, tags=["QC_OK", "batch a"], tag_op="or")
        run("tags_and_empty", limit=100, tags=["qc_ok", "Batch A"])
        run("stage_raw", limit=100, stage="raw")
        run("stage_derived", limit=100, stage="derived")
        run("stage_output_empty", limit=100, stage="output")
        run("type_unknown", limit=100, type="unknown")
        run("type_missing", limit=100, type="no-such-type")
        run("type_empty_string_filters_all", limit=100, type="")
        run("include_trashed", limit=100, include_trashed=True)
        run("trashed_only", limit=100, trashed_only=True)
        run("include_trashed_order_size", limit=100, include_trashed=True,
            order_by="size")
        run("asset_id_single", limit=100,
            asset_id=made["well_002"].asset_id)
        run("asset_ids_pair", limit=100,
            asset_ids=[made["well_002"].asset_id, made["well_005"].asset_id])
        run("offset_beyond_end", limit=5, offset=500)
        run("limit_zero", limit=0)
        run("default_limit500", limit=500)
    finally:
        service.close()

    oracle = {
        "scenario": "paged_queries",
        "queries": queries,
    }
    _write_oracle(scenario, oracle)


def _write_oracle(scenario: Path, oracle: dict) -> None:
    path = scenario / "oracle.json"
    path.write_text(
        json.dumps(oracle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"froze {path.relative_to(REPO)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=[
        "gc_orphans", "dedup_flow", "place_rules", "paged_queries"])
    args = parser.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    builders = {
        "gc_orphans": scenario_gc_orphans,
        "dedup_flow": scenario_dedup_flow,
        "place_rules": scenario_place_rules,
        "paged_queries": scenario_paged_queries,
    }
    if args.only:
        builders[args.only]()
    else:
        for build in builders.values():
            build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
