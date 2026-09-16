"""Generate the CPP-B fixture corpus with the REAL Python persistence.

Runs read-only on the main repo's interpreter (no installs); writes only
into this worktree's ``tests/cpp/data/fixtures``. Every fixture is produced
through the production code paths (ProjectManager.save, DataCatalogService)
so the C++ side is validated against reality, not a hand-copied schema.

Usage (from the MAIN repo root, or with PYTHONPATH pointing at it):

    <main>/.venv/Scripts/python.exe tools/oracle/generate_fixtures.py \
        --out <worktree>/tests/cpp/data/fixtures

Determinism: ids/timestamps that would default to now/uuid are set
explicitly. Derived fixtures keep the ``typical.*`` file names (tests glob
``*.paleo.json`` in each fixture directory).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

FIXED_TS = "2026-09-16T08:00:00.000000+00:00"
_SEQ = {"n": 0}


def _hex12(prefix: str) -> str:
    _SEQ["n"] += 1
    return f"{prefix}{_SEQ['n']:012d}"


def ts() -> str:
    return FIXED_TS


# -- project document builders ------------------------------------------------


def build_minimal():
    from paleo_workbench.project.models import ProjectDocument, ProjectMeta

    meta = ProjectMeta(name="极小工程", region="", version="0.2.17a0")
    meta.created_at = ts()
    meta.updated_at = ts()
    doc = ProjectDocument(meta=meta)
    doc.schema_version = 1
    return doc


def build_typical(fixdir: Path):
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.mapping_workspace.stage_state import (
        LayerMembershipRecord,
        MappingWorkspaceState,
    )
    from paleo_workbench.mapping_workspace.stages import MappingStage
    from paleo_workbench.project.domain import (
        DomainEntity,
        EntityAssetLink,
        SeismicSurveyEntity,
        WellEntity,
        WorkArea,
    )
    from paleo_workbench.project.models import (
        ExportArtifact,
        FactorMapTask,
        PaleoMapDocument,
        ProjectDocument,
        ProjectMeta,
        QualityReport,
        ResourceItem,
        UserVectorFeature,
        UserVectorLayer,
    )

    meta = ProjectMeta(name="典型工程-演示", region="鄂尔多斯盆地")
    meta.created_at = ts()
    meta.updated_at = ts()
    doc = ProjectDocument(meta=meta)
    doc.coordinate.project_crs = "EPSG:4547"
    doc.coordinate.crs_locked = True

    doc.workarea = WorkArea(
        id=_hex12("wa"),
        name="镇泾工区",
        boundary=[[100.0, 200.0], [110.0, 200.0], [110.0, 210.0], [100.0, 210.0]],
        boundary_crs="EPSG:4547",
        project_crs="EPSG:4547",
        created_at=ts(),
        updated_at=ts(),
    )
    doc.wells = [
        WellEntity(
            id=_hex12("well"), name="镇评1", uwi="ZP-0001",
            surface_x=451000.5, surface_y=3_880_100.25, source_crs="EPSG:4547",
            project_x=451000.5, project_y=3_880_100.25,
            coordinate_status="projected", kb=1050.0, td=2350.5,
            created_at=ts(), updated_at=ts(),
        ),
        WellEntity(
            id=_hex12("well"), name="ZP-2 井", aliases=["镇评2"],
            spatial_scope="reference", tags=["评价井"],
            created_at=ts(), updated_at=ts(),
        ),
    ]
    doc.seismic_surveys = [
        SeismicSurveyEntity(
            id=_hex12("svy"), name="镇泾三维", survey_type="3d",
            inline_range=[1000.0, 1500.0, 10.0],
            crossline_range=[500.0, 900.0, 10.0],
            n_samples=751, dt_ms=2.0,
            created_at=ts(), updated_at=ts(),
        )
    ]
    doc.geological_entities = [
        DomainEntity(id=_hex12("ent"), kind="geological", name="T1c7 层位",
                     entity_kind="horizon", created_at=ts(), updated_at=ts())
    ]
    doc.entity_asset_links = [
        EntityAssetLink(
            id=_hex12("link"), entity_type="well",
            entity_id=doc.wells[0].id, asset_id="asset_fixture_a",
            role="tops", is_primary=True, created_at=ts(),
        )
    ]
    # 内部资源（绝对路径输入 → save 时 relativize）+ 外部资源
    internal_payload = fixdir / "payloads" / "well_heads.csv"
    external_payload = fixdir / "payloads" / "external" / "segy" / "raw.sgy"
    doc.resources = [
        ResourceItem(
            id=_hex12("res"), name="井头数据.csv", path=str(internal_payload),
            type="well_head", format="csv", crs="EPSG:4547",
            tags=["井头"],
        ),
        ResourceItem(
            id=_hex12("res"), name="原始地震.sgy", path=str(external_payload),
            type="seismic", format="segy",
        ),
    ]
    doc.export_artifacts = [
        ExportArtifact(
            id=_hex12("artifact"), linked_id=doc.wells[0].id,
            format="pdf", output_path=str(fixdir / "payloads" / "exports" / "map.pdf"),
            generated_at=ts(), included_map_elements=["图例", "比例尺"],
        )
    ]
    doc.factor_map_tasks = [
        FactorMapTask(
            id=_hex12("factor"), name="砂厚趋势面", target_horizon="T1c7",
            factor_type="sand_thickness", method="idw",
            status="complete", source_kind="real",
            grid_artifact_path=str(fixdir / "payloads" / "grids" / "sand.npz"),
            parameters={"power": 2.5},
        )
    ]
    doc.user_vector_layers = [
        UserVectorLayer(
            id=_hex12("uvlayer"), name="物源线-A", geometry_kind="line",
            template="source_line", crs="EPSG:4547",
            features=[
                UserVectorFeature(
                    id=_hex12("feat"),
                    geometry={"type": "LineString",
                              "coordinates": [[0.0, 0.0], [1.5, 2.25]]},
                    properties={"label": "物源方向↗", "confidence": 0.9},
                )
            ],
        ),
        UserVectorLayer(id=_hex12("uvlayer"), name="相界多边形", geometry_kind="polygon"),
        UserVectorLayer(id=_hex12("uvlayer"), name="自由图层", template=""),
    ]
    doc.paleomap_documents = [
        PaleoMapDocument(
            id=_hex12("map"), name="T1c7 期岩相古地理",
            linked_target_horizon="T1c7",
            facies_polygons=[
                {"id": "p1", "facies": "辫状河三角洲",
                 "ring": [[0, 0], [2, 0], [2, 2]]}
            ],
            line_features=[{"id": "l1", "kind": "海岸线"}],
            map_crs="EPSG:4547",
        )
    ]
    doc.quality_reports = [
        QualityReport(
            id=_hex12("qc"), linked_map_document_id=doc.paleomap_documents[0].id,
            rules=["topology"], issues=[{"rule": "topology", "severity": "warning"}],
            status="complete", generated_at=ts(),
        )
    ]
    doc.map_qgis_project_xml = (
        '<!DOCTYPE qgis PROJECT><qgis projectname="典型工程" version="4.2.0">'
        "<projectlayers/><layer-tree-group/></qgis>"
    )

    ws = MappingWorkspaceState()
    ws.current_stage = MappingStage.CONSTRAINT_FACTOR
    view = ws.view_state(MappingStage.FACIES_CALIBRATION)
    view.group_visibility = {"factor_group": None, "qc_group": False}
    view.layer_visibility = {"L_drafted": True, "L_hidden": False}
    view.layer_opacity = {"L_drafted": 0.65, "L_null_drop": None}
    view.active_layer_id = "L_drafted"
    view.active_tool = "pan"
    view.customized = True
    for layer_id, role, task, bind in [
        ("L_drafted", LayerRole.INITIAL_FACIES_DRAFT, "",
         ("asset_fixture_a", "ver_fixture_a1", "catalog_version")),
        ("L_grid", LayerRole.FACTOR_GRID, "factor000000000001",
         ("asset_fixture_b", "ver_fixture_b1", "catalog_version")),
        ("L_constraint", LayerRole.FAULT_CONSTRAINT, "",
         ("", "", "content_fingerprint")),
        ("L_qc", LayerRole.QC_WARNING, "", ("", "", "")),
    ]:
        ws.memberships[layer_id] = LayerMembershipRecord(
            layer_id=layer_id, role=role, factor_task_id=task,
            created_stage="facies_calibration",
            source_asset_id=bind[0], source_version_id=bind[1],
            binding_kind=bind[2], bound_at=ts(), created_at=ts(),
        )
    ws.tree = {
        "order": ["L_drafted", "L_grid"],
        "groups": [{"id": "factor_group", "title": "单因素",
                    "children": ["L_grid"]}],
    }
    ws.artifact_maturity = {"factor000000000001": "reviewed", "map_draft": "draft"}
    ws.compilation_input_set = {"factor000000000001": "ver_fixture_b1"}
    doc.mapping_workspace = ws.to_dict()
    doc.compilation_input_sets = [
        {
            "id": "cis_000000000001", "name": "T1c7 编图输入",
            "status": "frozen",
            "entries": [{"asset_id": "asset_fixture_b",
                          "pinned_version_id": "ver_fixture_b1"}],
        }
    ]
    doc.onboarding_report = {"imported": 2, "skipped": 1}
    doc.geo3d_workspace.objects = [{"id": "g1", "kind": "horizon"}]
    # geo3d extra="allow"：未来键必须原样往返
    doc.geo3d_workspace.model_extra["future_probe_v2"] = {"keep": True}
    return doc


# -- catalog builder ----------------------------------------------------------


def build_catalog(fixdir: Path, project_path: Path) -> dict:
    """Populate a rich catalog through the real service; return counts."""
    from paleo_workbench.catalog.models import VersionMember
    from paleo_workbench.catalog.service import DataCatalogService

    payload_root = fixdir / "payloads"
    service = DataCatalogService.open(project_path)
    counts = {}
    try:
        raw1 = payload_root / "well_heads.csv"
        v1 = service.import_raw(raw1, name="井头数据", type="well_head",
                                format="csv")
        # 同资产第二版本（managed RAW 升版）
        raw1b = payload_root / "well_heads_v2.csv"
        v2 = service.register_version(
            v1.asset_id, raw1b, "raw", parent_version_ids=[v1.id],
            metadata={"name": "复核"},
        )
        # 外部引用版本
        ext = payload_root / "external" / "segy" / "raw.sgy"
        service.link_external(ext, name="外部地震体", type="seismic",
                              format="segy")
        # manual_edit run + DERIVED 版本（typed ports）
        from paleo_workbench.catalog.lifecycle import (
            complete_manual_edit_run,
            register_manual_edit_run,
        )

        run = register_manual_edit_run(
            service, source_version_ids=[v1.id], entity_type="well",
            entity_id="well_fixture", business_role="tops", actor="oracle",
        )
        derived_src = payload_root / "derived" / "tops_edited.json"
        v4 = service.register_version(
            v1.asset_id, derived_src, "derived",
            parent_version_ids=[v1.id], run_id=run.id,
        )
        complete_manual_edit_run(service, run.id,
                                 committed_version_ids=[v4.id])
        # bundle 版本（version_members）
        bundle_src = payload_root / "derived" / "bundle_index.json"
        v5 = service.register_version(
            v1.asset_id, bundle_src, "intermediate", parent_version_ids=[v2.id]
        )
        for ver in service.document.versions:
            if ver.id == v5.id:
                ver.members = [
                    VersionMember(name="index", rel_path="index.json",
                                  member_role="index", ordinal=0),
                    VersionMember(name="attrs", rel_path="attrs.parquet",
                                  member_role="attributes", ordinal=1,
                                  required=False),
                ]
        service._save()
        # 工作副本（checked_out 行保留）
        service.create_working_copy(v1.id)
        # staging lease（瞬态表占位行，模拟 in-flight）
        service._index.acquire_staging_lease(
            (service._staging_target("raw", v1.asset_id),)
        )
        # tag 关联
        service.add_tag("标志-Ω", asset_id=v1.asset_id)
        service.add_tag("版本标记", version_id=v2.id)
        counts = {
            "assets": len(service.document.assets),
            "versions": len(service.document.versions),
            "runs": len(service.document.runs),
            "tags": len(service.document.tags),
            "asset_tags": sum(len(v) for v in
                              service.document.asset_tags.values()),
        }
    finally:
        service.close()
    return counts


# -- fixture writers -----------------------------------------------------------


def write_project(fixdir: Path, name: str, doc) -> Path:
    from paleo_workbench.project.manager import ProjectManager

    project_path = fixdir / f"{name}.paleo.json"
    manager = ProjectManager(project_path)
    manager.save(doc)
    return project_path


def postprocess(fixdir: Path, name: str, kind: str) -> None:
    """Corrupt / future-schema post-processing on the saved fixture."""
    project_path = fixdir / f"{name}.paleo.json"
    if kind == "future":
        data = json.loads(project_path.read_text(encoding="utf-8"))
        data["schema_version"] = 99
        data["unknown_section_from_2099"] = {"payload": [1, 2, 3], "keep": True}
        project_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    elif kind == "corrupt_json":
        raw = project_path.read_text(encoding="utf-8")
        project_path.write_text(raw[: len(raw) // 2], encoding="utf-8")
    elif kind == "corrupt_db":
        db = fixdir / f"{name}.artifacts" / "metadata" / "catalog.sqlite"
        if db.is_file():
            blob = bytearray(db.read_bytes())
            for i in range(0, len(blob), 997):
                blob[i] = blob[i] ^ 0xFF
            db.write_bytes(bytes(blob))
    elif kind == "missing":
        data = json.loads(project_path.read_text(encoding="utf-8"))
        for res in data.get("resources", []):
            res["path"] = "payloads/does_not_exist.csv"
            res["external"] = False
        project_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_payloads(fixdir: Path) -> None:
    """Deterministic payload files referenced by the fixtures."""
    root = fixdir / "payloads"
    files = {
        "well_heads.csv": ("uwi,x,y\nZP-0001,451000.5,3880100.25\n"
                           "ZP-0002,452000.0,3881100.0\n", "utf-8"),
        "well_heads_v2.csv": ("uwi,x,y,kb\nZP-0001,451000.5,3880100.25,1050.0\n"
                              "ZP-0002,452000.0,3881100.0,990.0\n"
                              "ZP-0003,453000.0,3882100.0,1010.0\n", "utf-8"),
        "external/segy/raw.sgy": (b"\x00" * 512 + b"SEGY-ORACLE-FIXTURE"
                                  + b"\x01" * 128, None),
        "exports/map.pdf": (b"%PDF-1.7 oracle fixture\n", None),
        "grids/sand.npz": (b"PK\x03\x04oracle-npz-fixture", None),
        "derived/tops_edited.json": ('{"tops": [{"well": "ZP-0001", '
                                     '"md": 1234.5}]}', "utf-8"),
        "derived/bundle_index.json": ('{"index": "demo"}', "utf-8"),
    }
    for rel, (content, encoding) in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if encoding is None:
            target.write_bytes(content)
        else:
            target.write_text(content, encoding=encoding)


def _clear_readonly(func, target, exc):
    import os
    import stat

    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    func(target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        # RAW/blob payload 落盘即只读（storage.py 语义），重生成前先解位
        shutil.rmtree(out, onerror=_clear_readonly)
    out.mkdir(parents=True)

    # ---- minimal
    fixdir = out / "minimal"
    fixdir.mkdir()
    write_payloads(fixdir)
    write_project(fixdir, "minimal", build_minimal())

    # ---- typical (project + full catalog)
    fixdir = out / "typical"
    fixdir.mkdir()
    write_payloads(fixdir)
    typical = write_project(fixdir, "typical", build_typical(fixdir))
    counts = build_catalog(fixdir, typical)

    # ---- unicode_paths: 工程名/资源名全 Unicode
    fixdir = out / "unicode_paths"
    fixdir.mkdir()
    write_payloads(fixdir)
    doc = build_minimal()
    doc.meta.name = "中文路径工程·测试"
    from paleo_workbench.project.models import ResourceItem

    las_dir = fixdir / "payloads" / "曲线 目录"
    las_dir.mkdir(parents=True, exist_ok=True)
    (las_dir / "ZP-0001.LAS").write_text("~VERSION INFORMATION\n",
                                         encoding="utf-8")
    doc.resources = [
        ResourceItem(
            id=_hex12("res"), name="测井曲线.LAS",
            path="payloads/曲线 目录/ZP-0001.LAS",
            type="well_log", format="las",
        )
    ]
    write_project(fixdir, "unicode_paths", doc)

    # ---- legacy_abs_paths: 资源绝对路径（迁移机器）
    fixdir = out / "legacy_abs_paths"
    fixdir.mkdir()
    write_payloads(fixdir)
    doc = build_minimal()
    doc.meta.name = "旧版绝对路径工程"
    doc.resources = [
        ResourceItem(
            id=_hex12("res"), name="外部栅格.tif",
            path=str((fixdir / "payloads" / "external" / "segy" /
                      "raw.sgy").resolve()),
            type="raster", format="gtiff",
        )
    ]
    write_project(fixdir, "legacy_abs_paths", doc)

    # ---- future_schema / corrupt_json / corrupt_db / missing_resource
    # （从 typical 复制改造；保留 typical.* 文件名，测试按 glob 定位）
    for name, kind in [
        ("future_schema", "future"),
        ("corrupt_json", "corrupt_json"),
        ("corrupt_db", "corrupt_db"),
        ("missing_resource", "missing"),
    ]:
        dst = out / name
        shutil.copytree(out / "typical", dst)
        postprocess(dst, "typical", kind)

    # ---- manifest
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/oracle/generate_fixtures.py",
        "fixed_timestamp": FIXED_TS,
        "catalog_counts_typical": counts,
        "fixtures": {},
    }
    for fixture_dir in sorted(out.iterdir()):
        if not fixture_dir.is_dir():
            continue
        entries = {}
        for path in sorted(fixture_dir.rglob("*")):
            if path.is_file():
                entries[path.relative_to(fixture_dir).as_posix()] = sha256_of(path)
        manifest["fixtures"][fixture_dir.name] = entries
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"fixtures written to {out}")


if __name__ == "__main__":
    main()
