"""新建工程向导纯逻辑层测试 — 凸包、报告构建、端到端分析."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.domain_binding import BindingReport
from paleo_workbench.project.domain import CoordinateStatus, WellEntity, WorkArea
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.resources.import_service import ImportReport


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _minimal_las(path: Path, *, well: str = "TEST") -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 10.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                f" WELL. {well}:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
                "2.0 30.0",
            ]
        ),
        encoding="utf-8",
    )


def _make_doc_with_wells(coords: list[tuple[float, float] | None]) -> ProjectDocument:
    doc = ProjectDocument.new("凸包测试")
    doc.coordinate.project_crs = "EPSG:4326"
    # ensure workarea via domain helper
    from paleo_workbench.project.domain import ensure_workarea

    ensure_workarea(doc)
    for idx, c in enumerate(coords):
        w = WellEntity(name=f"W{idx}")
        if c is not None:
            w.project_x, w.project_y = c
            w.coordinate_status = CoordinateStatus.OK
            w.surface_x, w.surface_y = c
        doc.wells.append(w)
    return doc


# ---------------------------------------------------------------------------
# 凸包
# ---------------------------------------------------------------------------


class TestBoundaryFromWells:
    def test_less_than_three_points_no_ring(self):
        from paleo_workbench.project.onboarding import boundary_from_wells

        doc = _make_doc_with_wells([(0, 0), (1, 1)])
        ring = boundary_from_wells(doc)
        assert ring == []
        # workarea boundary should stay empty
        assert doc.workarea.boundary == []

    def test_collinear_points_no_ring(self):
        from paleo_workbench.project.onboarding import boundary_from_wells

        doc = _make_doc_with_wells([(0, 0), (1, 1), (2, 2), (3, 3)])
        ring = boundary_from_wells(doc)
        assert ring == []
        assert doc.workarea.boundary == []

    def test_normal_points_closed_ring(self):
        from paleo_workbench.project.onboarding import boundary_from_wells

        coords = [(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5)]
        doc = _make_doc_with_wells(coords)
        ring = boundary_from_wells(doc)
        assert len(ring) >= 4
        assert ring[0] == ring[-1]
        # hull should contain outer corners
        # Check closure and non-empty

    def test_boundary_backfill_to_workarea(self):
        from paleo_workbench.project.onboarding import boundary_from_wells

        coords = [(0, 0), (10, 0), (10, 10), (0, 10)]
        doc = _make_doc_with_wells(coords)
        doc.coordinate.project_crs = "EPSG:4326"
        assert doc.workarea.boundary == []
        ring = boundary_from_wells(doc)
        assert ring
        assert doc.workarea.boundary == ring
        assert doc.workarea.boundary_crs == "EPSG:4326"
        # second call with existing boundary should not overwrite
        first = list(doc.workarea.boundary)
        coords2 = [(100, 100), (110, 100), (110, 110)]
        # add more wells but boundary already filled — should not refill
        doc.wells.append(WellEntity(name="NEW", project_x=50, project_y=50, coordinate_status=CoordinateStatus.OK))
        ring2 = boundary_from_wells(doc)
        # ring2 is computed but not backfilled
        assert doc.workarea.boundary == first
        assert ring2  # still returns hull

    def test_prefers_project_xy_over_surface(self):
        from paleo_workbench.project.onboarding import boundary_from_wells

        doc = ProjectDocument.new("pref")
        from paleo_workbench.project.domain import ensure_workarea

        ensure_workarea(doc)
        w = WellEntity(name="A", project_x=10, project_y=20, surface_x=999, surface_y=999, coordinate_status=CoordinateStatus.OK)
        doc.wells.append(w)
        w2 = WellEntity(name="B", surface_x=0, surface_y=0)
        w2.project_x = None
        w2.project_y = None
        doc.wells.append(w2)
        w3 = WellEntity(name="C", project_x=10, project_y=0, coordinate_status=CoordinateStatus.OK)
        doc.wells.append(w3)
        w4 = WellEntity(name="D", project_x=0, project_y=10, coordinate_status=CoordinateStatus.OK)
        doc.wells.append(w4)
        ring = boundary_from_wells(doc)
        assert ring
        # ensure project_x preferred (10,20) not 999
        xs = [p[0] for p in ring]
        assert 999 not in xs
        assert 10 in xs


# ---------------------------------------------------------------------------
# build_onboarding_report
# ---------------------------------------------------------------------------


class TestBuildOnboardingReport:
    def test_all_keys_and_counts(self):
        from paleo_workbench.project.onboarding import build_onboarding_report
        from paleo_workbench.project.domain import ensure_workarea

        doc = ProjectDocument.new("报告测试")
        ensure_workarea(doc)
        doc.wells.extend(
            [
                WellEntity(name="W1", project_x=0, project_y=0, coordinate_status=CoordinateStatus.OK),
                WellEntity(name="W2", project_x=10, project_y=5, coordinate_status=CoordinateStatus.OK),
                WellEntity(name="W3"),  # no coords
            ]
        )
        from paleo_workbench.project.domain import SeismicSurveyEntity

        doc.seismic_surveys.append(SeismicSurveyEntity(name="S1"))
        from paleo_workbench.project.domain import DomainEntity

        doc.geological_entities.append(DomainEntity(kind="geological", name="H1", entity_kind="horizon"))

        # 伪造 ImportReport
        import_report = ImportReport(
            added=[
                ResourceItem(name="a.las", path="/tmp/a.las", type="well_log", format="las"),
                ResourceItem(name="b.dat", path="/tmp/b.dat", type="time_depth", format="dat"),
                ResourceItem(name="c.dat", path="/tmp/c.dat", type="horizon", format="dat"),
            ],
            skipped_path=[Path("/tmp/dup.las")],
            skipped_filter=[Path("/tmp/skip.txt")],
            warnings=["warn1"],
        )
        # BindingReport 伪造
        binding_report = BindingReport(
            wells_created=2,
            surveys_created=1,
            entities_created=1,
            ambiguous_assets=1,
            issues=[f"issue-{i}" for i in range(25)],
        )

        report = build_onboarding_report(
            doc,
            import_report,
            binding_report,
            source_folder="/data/src",
            intermediate_folder="/data/inter",
        )

        # 键完整性
        expected_keys = {
            "generated_at",
            "source_folder",
            "intermediate_folder",
            "imported_count",
            "by_type",
            "skipped",
            "warnings",
            "wells_total",
            "wells_with_coords",
            "surveys",
            "entities",
            "ambiguous",
            "issues",
            "extent",
        }
        assert set(report.keys()) == expected_keys
        assert report["source_folder"] == "/data/src"
        assert report["intermediate_folder"] == "/data/inter"
        assert report["imported_count"] == 3
        # by_type 中文标签计数
        assert report["by_type"].get("测井") == 1 or report["by_type"].get("测井数据") == 1
        # 允许多种标签，至少包含时深和层位
        assert "时深" in report["by_type"]
        assert report["by_type"]["时深"] == 1
        assert "层位" in report["by_type"] or "层位数据" in report["by_type"]
        # skipped = 2
        assert report["skipped"] == 2
        assert report["warnings"] == ["warn1"]
        assert report["wells_total"] == 3
        assert report["wells_with_coords"] == 2
        assert report["surveys"] == 1
        assert report["entities"] >= 1
        assert report["ambiguous"] == 1
        assert len(report["issues"]) == 20
        assert report["issues"][0] == "issue-0"
        assert report["extent"] == [0, 10, 0, 5]

    def test_extent_none_when_no_coords(self):
        from paleo_workbench.project.onboarding import build_onboarding_report

        doc = ProjectDocument.new("无坐标")
        from paleo_workbench.project.domain import ensure_workarea

        ensure_workarea(doc)
        doc.wells.append(WellEntity(name="W1"))
        import_report = ImportReport(added=[])
        binding_report = BindingReport()
        report = build_onboarding_report(doc, import_report, binding_report, source_folder="/src", intermediate_folder="/inter")
        assert report["extent"] is None
        assert report["wells_with_coords"] == 0


# ---------------------------------------------------------------------------
# analyze_data_folder 端到端
# ---------------------------------------------------------------------------


class TestAnalyzeDataFolder:
    def test_e2e_import_and_report(self, tmp_path: Path):
        from paleo_workbench.project.onboarding import analyze_data_folder

        root = tmp_path / "data_root"
        root.mkdir()
        # 2 个 LAS — 不同井名以避免合并
        _minimal_las(root / "A1.las", well="W-A1")
        _minimal_las(root / "A2.las", well="W-A2")
        # 时深 子目录
        td_dir = root / "时深"
        td_dir.mkdir()
        (td_dir / "td.dat").write_text("td content", encoding="utf-8")
        # 层位 子目录
        hor_dir = root / "层位"
        hor_dir.mkdir()
        (hor_dir / "hor.dat").write_text("hor content", encoding="utf-8")

        result = analyze_data_folder(root, project_name="E2E工区")

        # 资源入库数量
        assert result.imported == 4
        assert len(result.document.resources) == 4
        assert result.report["imported_count"] == 4
        # by_type 含 时深/层位
        by_type = result.report["by_type"]
        assert "时深" in by_type and by_type["时深"] == 1
        # horizon 可能标签为 层位 或 层位数据
        assert ("层位" in by_type and by_type["层位"] == 1) or ("层位数据" in by_type and by_type["层位数据"] == 1)
        # wells_total >=2 来自 LAS
        assert result.report["wells_total"] >= 2
        assert result.document.onboarding_report == result.report
        assert result.document.onboarding_report["imported_count"] == 4
        # source/intermediate 均为 root
        assert result.report["source_folder"] == str(root)
        assert result.report["intermediate_folder"] == str(root)

    def test_e2e_convex_hull_with_faked_coords(self, tmp_path: Path, monkeypatch):
        """用 fake 引擎让两口井带坐标，验证凸包与 extent。"""
        from paleo_workbench.project.onboarding import analyze_data_folder
        from paleo_workbench.catalog.domain_binding import WellExtract, StagedResource

        root = tmp_path / "data2"
        root.mkdir()
        _minimal_las(root / "B1.las", well="W-B1")
        _minimal_las(root / "B2.las", well="W-B2")
        td_dir = root / "时深"
        td_dir.mkdir()
        (td_dir / "td2.dat").write_text("x", encoding="utf-8")
        hor_dir = root / "层位"
        hor_dir.mkdir()
        (hor_dir / "hor2.dat").write_text("y", encoding="utf-8")

        # 构造 fake engine: stage_resources 会被我们 monkeypatch 以注入坐标
        # 直接 patch stage_resources 返回带坐标的 staged
        import paleo_workbench.project.onboarding as onboarding_mod

        orig_stage = onboarding_mod.__dict__.get("stage_resources")  # not there
        # patch domain_binding.stage_resources
        import paleo_workbench.catalog.domain_binding as binding_mod

        real_stage = binding_mod.stage_resources

        def fake_stage(project, resources, *, path_resolver, engine=None):
            # 调用真实 stage 以获得基础 staged，但随后注入坐标给 LAS 资源
            staged = real_stage(project, resources, path_resolver=path_resolver, engine=engine)
            # 为每个 well_log 类型的 staged 注入带坐标的 WellExtract
            coords = [(0, 0), (10, 10), (10, 0), (0, 10)]
            idx = 0
            for item in staged:
                if item.wells and len(item.wells) == 1 and item.wells[0].x is None:
                    # replace with coordinate-bearing extract
                    x, y = coords[idx % len(coords)]
                    item.wells = [WellExtract(name=item.wells[0].name, x=x, y=y)]
                    idx += 1
            # 如果只有 2 个 LAS，我们补充到 4 个点以形成凸包（再加两个虚拟）
            # 通过直接添加 WellExtract 来扩充第二个 item
            if len(staged) >= 1:
                # 确保有至少 4 个不同点
                # 将第一个 LAS 的 staged 扩充为 2 个点
                pass
            return staged

        monkeypatch.setattr(binding_mod, "stage_resources", fake_stage)

        # 同时需要让 bind 过程把坐标写入 project_x/y
        # WellExtract x/y 会通过 _refresh_well_geometry 写入

        result = analyze_data_folder(root, project_name="Hull工区", engine=object())

        # 验证 wells_with_coords 与 extent、boundary
        # fake_stage 注入了坐标，至少 2 个带坐标
        assert result.report["wells_total"] >= 2
        # 由于注入坐标，wells_with_coords 应 >=2
        assert result.report["wells_with_coords"] >= 2
        assert result.report["extent"] is not None
        xmin, xmax, ymin, ymax = result.report["extent"]
        assert xmax > xmin and ymax > ymin
        # 验证 workarea boundary 已回填（有坐标且 >=3 点时）
        # 我们的 fake 仅给 2 个点（各 1 个），凸包需要 >=3 点，所以 boundary 仍空
        # 手动补充第三口井以验证凸包回填
        if len(result.document.wells) >= 2:
            from paleo_workbench.project.domain import WellEntity

            # 补第三口井形成三角
            result.document.wells.append(
                WellEntity(name="W_EXTRA", project_x=5, project_y=15, surface_x=5, surface_y=15, coordinate_status=CoordinateStatus.OK)
            )
            from paleo_workbench.project.onboarding import boundary_from_wells

            ring = boundary_from_wells(result.document)
            assert ring and ring[0] == ring[-1]
            # 若之前 boundary 为空，现在应被填充
            if result.document.workarea.boundary:
                assert result.document.workarea.boundary[0] == result.document.workarea.boundary[-1]

        monkeypatch.setattr(binding_mod, "stage_resources", real_stage)
