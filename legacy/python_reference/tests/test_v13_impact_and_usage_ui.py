"""V13 impact 预览门 + 检查器地图用途行（W-C/W-F/W-M）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.mapping_workspace.stage_state import (
    BINDING_CATALOG_VERSION,
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.impact_preview_dialog import collect_trash_impact


@pytest.fixture(autouse=True)
def _clean_catalog_runtime():
    reset_catalog()
    yield
    reset_catalog()


@pytest.fixture()
def env(tmp_path: Path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    doc = ProjectDocument.new("demo")
    doc.meta.project_root = str(project_path.parent)
    yield service, doc, project_path.parent
    reset_catalog()
    service.close()


def _raw(service, tmp_path, name):
    src = tmp_path / name
    src.write_text(f"raw-{name}", encoding="utf-8")
    return service.import_raw(src, name=name, type="well_log")


def _derived(service, tmp_path, name, parent_version):
    src = tmp_path / f"{name}.out"
    src.write_text(f"derived-{name}", encoding="utf-8")
    run = service.register_run("demo_op", input_version_ids=[parent_version.id])
    return service.register_result_asset(
        name=name, type="derived", format="txt", asset_metadata=None,
        source_path=src, stage="derived", run_id=run.id,
    )


class TestTrashImpactCollection:
    def test_collect_impact_aggregates_descendants_and_map_usages(self, env):
        service, doc, tmp_path = env
        raw = _raw(service, tmp_path, "a.las")
        _derived(service, tmp_path, "pred", raw)
        workspace = MappingWorkspaceState()
        workspace.set_membership(LayerMembershipRecord(
            layer_id="layer-x",
            source_version_id=raw.id, source_asset_id=raw.asset_id,
            binding_kind=BINDING_CATALOG_VERSION,
        ))
        summary = collect_trash_impact(
            service, doc, asset_ids=[raw.asset_id], workspace=workspace)
        assert summary.descendant_count >= 1
        assert ("layer", "图层 layer-x") in summary.map_usages
        assert summary.has_downstream
        markdown = summary.render_markdown()
        assert "编图图层正在引用" in markdown
        assert "个活跃下游版本" in markdown

    def test_collect_impact_silent_when_isolated(self, env):
        service, doc, tmp_path = env
        raw = _raw(service, tmp_path, "solo.las")
        summary = collect_trash_impact(
            service, doc, asset_ids=[raw.asset_id], workspace=None)
        assert not summary.has_downstream
        assert "可以安全移出" in summary.render_markdown()


class TestRemoveAssetsImpactGate:
    def _make_page(self, qtbot, env):
        from paleo_workbench.ui.pages.data_page import DataPage

        service, doc, tmp_path = env
        page = DataPage(project=doc)
        qtbot.addWidget(page)
        return page, service

    def test_declined_confirmation_aborts_trash(self, qtbot, env, monkeypatch):
        page, service = self._make_page(qtbot, env)
        raw = _raw(service, Path(page.project.meta.project_root), "gated.las")
        _derived(service, Path(page.project.meta.project_root), "child", raw)
        asset = service.get_asset(raw.asset_id)

        called = {"n": 0}

        def fake_confirm(*args, **kwargs):
            called["n"] += 1
            return False

        monkeypatch.setattr(
            "paleo_workbench.ui.pages.impact_preview_dialog.confirm_trash_impact",
            fake_confirm,
        )
        ok = page._lifecycle.remove_assets([asset])
        assert ok is False
        assert called["n"] == 1
        assert service.get_asset(raw.asset_id).trashed is False

    def test_no_impact_removes_without_dialog(self, qtbot, env):
        page, service = self._make_page(qtbot, env)
        raw = _raw(service, Path(page.project.meta.project_root), "free.las")
        asset = service.get_asset(raw.asset_id)
        # 不 monkeypatch：若影响预览弹了模态窗，offscreen 下 exec() 会挂起
        # 本用例（timeout）；顺利返回即证明无影响路径静默放行。
        ok = page._lifecycle.remove_assets([asset])
        assert ok is True
        assert service.get_asset(raw.asset_id).trashed is True


class TestInspectorMapUsageRows:
    def test_usage_rows_render_layers_and_products(self, qtbot, env):
        from paleo_workbench.mapping_workspace.source_usage import usages_of_asset
        from paleo_workbench.ui.pages.inspector_panel import InspectorPanel

        service, doc, tmp_path = env
        raw = _raw(service, tmp_path, "u.las")
        workspace = MappingWorkspaceState()
        workspace.set_membership(LayerMembershipRecord(
            layer_id="layer-u", source_version_id=raw.id,
            source_asset_id=raw.asset_id,
            binding_kind=BINDING_CATALOG_VERSION,
        ))

        def provider(asset_id):
            return usages_of_asset(
                asset_id, workspace=workspace, project=doc, catalog=service)

        panel = InspectorPanel()
        qtbot.addWidget(panel)
        assert panel._map_usage_rows(SimpleNamespace(id=raw.asset_id)) == []
        panel.set_map_usage_provider(provider)
        rows = panel._map_usage_rows(SimpleNamespace(id=raw.asset_id))
        assert rows == [("编图图层引用", "1 个（图层 layer-u）")]

    def test_usage_rows_absent_when_no_provider(self, qtbot, env):
        from paleo_workbench.ui.pages.inspector_panel import InspectorPanel

        service, doc, tmp_path = env
        raw = _raw(service, tmp_path, "n.las")
        panel = InspectorPanel()
        qtbot.addWidget(panel)
        assert panel._map_usage_rows(SimpleNamespace(id=raw.asset_id)) == []
