#!/usr/bin/env python3
"""Freeze ingest-plan oracles for data.ingest_plan (conv-26).

Runs the REAL Python stack — DataCatalogService + resources/ingest_plan.py
(build + execute) — over deterministic scenario trees, then freezes the pure
plan projections, the id/time-masked execute reports and the post-execute
store/page/link structure into ``tests/cpp/data/fixtures/ingest_plan/``.
The C++ test copies the PRE-execute tree, replays build+execute through
pwb::data and must reproduce every frozen value after applying the SAME
masker to its own output.

Masking contract (applied by this generator and mirrored in the C++ test):
entity ids ``<kind>_<12 hex>`` (asset/ver/run/well/ent/svy/link/wa) become
``<kind>#<first-seen ordinal>``; ISO timestamps become ``<TS>``; absolute
scenario-root paths become ``<ROOT>``. No hand-written expected values —
every expectation comes from real module output. Re-running the script
reproduces byte-identical oracle.json (plan is pure; execute projections are
masked), which is the determinism proof.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Freeze the engine-missing fallback as the long-term C++ semantic (same
# boundary CONV-19 declared): block the geoviz LAS/WITSML engines so
# _extract_well_name walks its documented fallback chain.
sys.modules["geoviz"] = None

from paleo_workbench.catalog.service import DataCatalogService  # noqa: E402
from paleo_workbench.project.manager import ProjectManager  # noqa: E402
from paleo_workbench.resources.ingest_plan import (  # noqa: E402
    build_ingest_plan,
    execute_ingest_plan,
)

OUT_ROOT = REPO / "tests" / "cpp" / "data" / "fixtures" / "ingest_plan"

_ID_RE = re.compile(r"(asset|ver|run|well|ent|svy|link|wa)_[0-9a-f]{12}")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")


def _mask_string(text: str, counters: dict) -> str:
    def repl(match: re.Match) -> str:
        kind = match.group(1)
        key = (kind, match.group(0))
        if key not in counters:
            counters[key] = f"{kind}#{sum(1 for k in counters if k[0] == kind)}"
        return counters[key]

    return _TS_RE.sub("<TS>", _ID_RE.sub(repl, text))


def mask(value, root: Path, counters: dict | None = None):
    counters = counters if counters is not None else {}
    if hasattr(value, "model_dump"):  # pydantic v2 models
        value = value.model_dump()
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, dict):
        return {
            (mask(k, root, counters) if isinstance(k, str) else k): mask(
                v, root, counters)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask(v, root, counters) for v in value]
    if isinstance(value, str):
        value = value.replace(str(root), "<ROOT>")
        return _mask_string(value, counters)
    return value


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_files(root: Path) -> list[str]:
    # Store bookkeeping + the incoming source dir are not subjects of the
    # post-execute tree comparison (payload layout is compared instead).
    excluded = [
        root / "demo.artifacts" / "metadata",
        root / "incoming",
    ]
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
        and not any(base in p.resolve().parents for base in excluded)
    )


def _write_seed_project(tree: Path, wells: list[dict], surveys: list[dict]) -> None:
    manager = ProjectManager(tree / "demo.paleo.json")
    from paleo_workbench.project.models import ProjectDocument, ProjectMeta
    from paleo_workbench.project.domain import SeismicSurveyEntity, WellEntity

    document = ProjectDocument(meta=ProjectMeta(name="demo", region=""))
    document.wells = [
        WellEntity(id=w["id"], name=w["name"], uwi=w.get("uwi", ""))
        for w in wells
    ]
    document.seismic_surveys = [
        SeismicSurveyEntity(id=s["id"], name=s["name"]) for s in surveys
    ]
    document.entity_asset_links = []
    manager.save(document)


def build_scenario_tree(scenario: Path) -> Path:
    tree = scenario / "tree"
    shutil.rmtree(scenario, ignore_errors=True)
    (tree / "incoming").mkdir(parents=True)
    root = tree.resolve()

    wells_dir = tree / "incoming" / "W-01"
    wells_dir.mkdir()
    (wells_dir / "curves.las").write_bytes(b"las-bytes-w01")
    (tree / "incoming" / "W-02").mkdir()
    (tree / "incoming" / "W-02" / "curves.las").write_bytes(b"las-bytes-w02")
    # Tops (csv → role tops via filename token), deviation-like spreadsheet.
    (tree / "incoming" / "W-01" / "tops.csv").write_bytes(b"formation,tops\nF1,10\n")
    (tree / "incoming" / "W-01" / "deviation.xlsx").write_bytes(b"xlsx-deviation")
    # Survey volume: file stem matches a registered survey name.
    (tree / "incoming" / "Gulf3D.sgy").write_bytes(b"sgy-bytes")
    # Shapefile family (adopts non-preferred sidecars wholesale).
    for ext, payload in (
        (".shp", b"shp"),
        (".shx", b"shx"),
        (".dbf", b"dbf"),
        (".prj", b"prj"),
    ):
        (tree / "incoming" / f"boundary{ext}").write_bytes(payload)
    # Non-preferred + filtered-out cases.
    (tree / "incoming" / "readme.foo").write_bytes(b"not preferred")
    (tree / "incoming" / "empty.dat").write_bytes(b"")
    (tree / "incoming" / "._junk.dat").write_bytes(b"mac resource fork")
    return root


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    scenario = OUT_ROOT / "main"
    tree = build_scenario_tree(scenario)
    root = tree.resolve()

    _write_seed_project(
        tree,
        wells=[
            {"id": "well_000000000001", "name": "W-01", "uwi": ""},
            {"id": "well_000000000002", "name": "Other-9", "uwi": ""},
        ],
        surveys=[{"id": "svy_000000000001", "name": "Gulf3D"}],
    )

    # Pre-seed one duplicate: the same source path + content as a planned
    # file, imported through the real service (managed RAW identity).
    service = DataCatalogService.open(tree / "demo.paleo.json", sweep_temp=False)
    try:
        duplicate_source = tree / "incoming" / "W-02" / "curves.las"
        service.import_raw(duplicate_source, name="curves.las")
    finally:
        service.close()
    _checkpoint(tree / "demo.artifacts" / "metadata" / "catalog.sqlite")

    # The committed fixture stays at the PRE-execute state: run the whole
    # plan+execute flow on a scratch COPY and freeze only its projections.
    exec_root = Path(tempfile.mkdtemp(prefix="pwb_ingest_exec_"))
    try:
        shutil.copytree(tree, exec_root / "tree")
        run_flow(exec_root / "tree", scenario)
    finally:
        shutil.rmtree(exec_root, ignore_errors=True)
    print(f"froze {(scenario / 'oracle.json').relative_to(REPO)}")
    return 0


def _checkpoint(sqlite_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def _relocate_source_uris(sqlite_path: Path, old_root: Path,
                           new_root: Path) -> None:
    """Point the seeded RAW identity at the replay location.

    The managed-RAW duplicate identity is (resolved source path, sha); the
    fixture was seeded at the canonical fixture path, so both this exec copy
    and the C++ replay rewrite source_uri to their own root before planning
    (project-relocation semantics; identical harness step on both sides).
    """
    import sqlite3

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(
            "UPDATE versions SET source_uri = replace(source_uri, ?, ?)",
            (str(old_root), str(new_root)),
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def run_flow(tree: Path, scenario: Path) -> None:
    import sqlite3  # noqa: F401  (checkpoint below)

    root = tree.resolve()
    _relocate_source_uris(
        tree / "demo.artifacts" / "metadata" / "catalog.sqlite",
        (scenario / "tree").resolve(),
        root,
    )
    manager = ProjectManager(tree / "demo.paleo.json")
    project = manager.load()

    # ---- phase 1: pure plan ----------------------------------------------
    # One shared id-counter table across every frozen section so cross
    # references (page rows ↔ links ↔ payload paths) stay consistent.
    counters: dict = {}
    service = DataCatalogService.open(tree / "demo.paleo.json", sweep_temp=False)
    try:
        plan = build_ingest_plan(tree / "incoming", project, service=service)
        plan_json = mask(plan.to_dict(), root, counters)
        summary_json = mask(plan.summary(), root, counters)

        # ---- phase 2: confirmed execute -----------------------------------
        for item in plan.items:
            if item.decision == "pending":
                item.decision = "accept"
        report = execute_ingest_plan(plan, service, project, bind=True)
        report_json = mask(
            {
                "imported_version_ids": report.imported_version_ids,
                # path-sorted so the id-mask counters match the C++ side's
                # ordered map projection (both freeze lowest-path first).
                "asset_id_by_path": dict(sorted(report.asset_id_by_path.items())),
                "bound_links": report.bound_links,
                "created_entities": report.created_entities,
                "skipped": report.skipped,
                "issues": report.issues,
                "cancelled": report.cancelled,
            },
            root,
            counters,
        )
        page = mask(
            service.search_assets_page(limit=100, order_by="name"), root,
            counters,
        )
        # Page order tails with the asset id; rows sharing a name tie-break
        # on a RANDOM id, so canonicalize equal-name groups by content (the
        # name order itself is untouched). The C++ replay applies the same
        # canonicalization before comparing.
        page = sorted(
            page, key=lambda row: (row["name"], json.dumps(row, sort_keys=True))
        )
        manager.save(project)

        links = mask(project.entity_asset_links, root, counters)
        wells = mask(project.wells, root, counters)
        surveys = mask(project.seismic_surveys, root, counters)
        entities = mask(project.geological_entities, root, counters)
        # Payload layout proof: random asset/ver dir ids collapse to <ID>
        # (counters cannot work here — the raw sort order itself is random);
        # blob paths are content-derived and stay verbatim.
        tree_files = sorted(
            _ID_RE.sub("<ID>", entry) for entry in _tree_files(root)
        )

        # ---- idempotent re-run (interrupted-import recovery contract) -----
        plan2 = build_ingest_plan(tree / "incoming", project, service=service)
        for item in plan2.items:
            if item.decision == "pending":
                item.decision = "accept"
        report2 = execute_ingest_plan(plan2, service, project, bind=True)
        rerun_json = mask(
            {
                "imported_version_ids": report2.imported_version_ids,
                "skipped": report2.skipped,
                "issues": report2.issues,
                "cancelled": report2.cancelled,
            },
            root,
            counters,
        )
    finally:
        service.close()

    oracle = {
        "scenario": "ingest_plan",
        "plan": plan_json,
        "summary": summary_json,
        "execute_report": report_json,
        "asset_page_after": page,
        "links_after": links,
        "wells_after": wells,
        "surveys_after": surveys,
        "geological_after": entities,
        "tree_files_after": tree_files,
        "rerun_report": rerun_json,
        "fixture_sha256": {
            "w02_curves": _sha_bytes(tree / "incoming" / "W-02" / "curves.las"),
        },
    }
    target = scenario / "oracle.json"
    target.write_text(
        json.dumps(oracle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"froze {target.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
