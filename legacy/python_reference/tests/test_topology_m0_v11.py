"""V11 拓扑迁移 M0 合同（#1285 CRS 契约 + #1283 全或无保存）。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.mapping_workspace.crs_gate import (
    collect_crs_mismatches,
    feature_bounds,
    is_geographic_declaration,
    validate_crs_domain,
)
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController


# -- CRS 域校验（纯函数） -------------------------------------------------------


class TestCrsDomainValidation:
    def test_geographic_declaration_detection(self):
        assert is_geographic_declaration("EPSG:4326")
        assert is_geographic_declaration("epsg:4490")
        assert is_geographic_declaration("+proj=longlat +datum=WGS84")
        assert not is_geographic_declaration("EPSG:3857")
        assert not is_geographic_declaration("")
        assert not is_geographic_declaration("LOCAL")

    def test_local_coords_with_geographic_declaration_mismatch(self):
        # 已知事故形态：声明 4326 + 数据 0-16000 本地坐标
        check = validate_crs_domain(
            "EPSG:4326", (0.0, 0.0, 16000.0, 9000.0))
        assert check.ok is False
        assert check.geographic_declared is True
        assert "EPSG:4326" in check.reason
        assert "本地坐标" in check.reason
        assert check.fix_options == ("declare_local", "clear")

    def test_geographic_data_passes(self):
        check = validate_crs_domain("EPSG:4326", (100.0, 30.0, 112.0, 38.0))
        assert check.ok is True

    def test_no_declaration_passes(self):
        check = validate_crs_domain("", (0.0, 0.0, 16000.0, 9000.0))
        assert check.ok is True
        assert check.geographic_declared is False

    def test_no_bounds_passes(self):
        assert validate_crs_domain("EPSG:4326", None).ok is True

    def test_small_overflow_within_slack_passes(self):
        # 球面环绕溢出 ≤1° 不算失配
        assert validate_crs_domain("EPSG:4326", (-180.5, -30.0, 180.5, 30.0)).ok

    def test_project_open_sweep(self):
        layers = [
            ("ok", "EPSG:4326", [[100.0, 30.0], [110.0, 35.0]]),
            ("bad", "EPSG:4326", [[0.0, 0.0], [16000.0, 9000.0]]),
            ("local", "", [[0.0, 0.0], [5000.0, 5000.0]]),
        ]
        mismatches = collect_crs_mismatches(layers)
        assert set(mismatches) == {"bad"}
        assert "本地坐标" in mismatches["bad"].reason

    def test_feature_bounds(self):
        assert feature_bounds([[1, 2], [3, 4]]) == (1.0, 2.0, 3.0, 4.0)
        assert feature_bounds([]) is None


# -- 编辑入口门禁 + 引导修复 ------------------------------------------------------


class _Canvas:
    def set_current_layer(self, doc_id):
        pass

    def setFocus(self):
        pass

    def setCursor(self, *a, **k):
        pass

    @property
    def native_tool_busy(self):
        return False


@pytest.fixture()
def controller(qapp):
    ctl = CompositeEditController(project_crs="EPSG:4326")
    ctl._canvas = _Canvas()
    return ctl


def _local_layer(ctl, layer_id="local_layer", crs=""):
    """本地坐标图层（默认无声明；crs="EPSG:4326" 构造失配场景）。"""
    features = (
        VectorFeature("f1", {"type": "Polygon", "coordinates":
                             [[[0.0, 0.0], [16000.0, 0.0], [16000.0, 9000.0],
                               [0.0, 0.0]]]}, {}),
    )
    layer = VectorLayer(id=layer_id, name=layer_id, crs=crs, features=features)
    ctl._layers[layer_id] = layer
    ctl._kinds[layer_id] = "polygon"
    return layer


class TestPreEntryGate:
    def test_mismatch_blocks_start_editing(self, controller):
        layer = _local_layer(controller, crs="EPSG:4326")
        controller.set_active_layer(layer.id)
        controller.start_editing()
        assert layer.edit_session is None  # 阻止进入编辑
        check = controller.last_crs_gate_check
        assert check is not None and check.ok is False

    def test_guided_fix_unblocks(self, controller):
        layer = _local_layer(controller, crs="EPSG:4326")
        controller.set_active_layer(layer.id)
        controller.start_editing()
        assert layer.edit_session is None
        assert controller.apply_crs_fix(layer.id, "declare_local") is True
        assert layer.crs == ""
        # 修复后（层声明已清空；项目声明为地理但层已本地化 → 层声明为准）
        controller.start_editing()
        assert layer.edit_session is not None

    def test_ensure_layer_session_gated(self, controller):
        layer = _local_layer(controller, crs="EPSG:4326")
        session, reason = controller.ensure_layer_session(layer.id)
        assert session is None
        assert "本地坐标" in reason

    def test_session_crs_freeze(self, controller):
        layer = _local_layer(controller)  # 无声明（本地）→ 门禁放行
        controller.project_crs = ""
        controller.set_active_layer(layer.id)
        controller.start_editing()
        assert layer.edit_session is not None
        ok, reason = controller.apply_project_crs("EPSG:4326")
        assert ok is False and "冻结" in reason
        assert controller.project_crs == ""
        # 无会话 → 放行
        layer.edit_session.commit_changes()
        ok2, _ = controller.apply_project_crs("EPSG:4326")
        assert ok2 is True


class TestAllOrNothingSave:
    def _two_sessions(self, controller):
        controller.project_crs = ""
        a = _local_layer(controller, "A")
        b = _local_layer(controller, "B")
        controller.set_active_layer("A")
        controller.start_editing()
        controller.set_active_layer("B")
        controller.start_editing()
        assert a.edit_session is not None and b.edit_session is not None
        return a, b

    def test_gate_failure_keeps_all_open(self, controller, monkeypatch):
        a, b = self._two_sessions(controller)
        # B 的角色门禁拒绝 → 全体不提交（blocked），A 的会话保持打开
        def gate(layer_id):
            return (False, "RAW 保护") if layer_id == "B" else (True, "")

        monkeypatch.setattr(controller, "can_edit_layer", gate)
        committed, blocked = controller.flush_edit_sessions()
        assert committed == 0
        assert len(blocked) == 1 and "RAW" in blocked[0]
        assert a.edit_session is not None and b.edit_session is not None

    def test_commit_failure_rolls_back_remainder(self, controller, monkeypatch):
        a, b = self._two_sessions(controller)
        # A 提交抛异常 → A 已提交数为 0 且 B 回滚（全或无）
        import paleo_workbench.mapping.vector_layer as vl

        real_commit = vl.VectorEditSession.commit_changes

        def boom(self):
            if self is a.edit_session:
                raise RuntimeError("commit boom")
            return real_commit(self)

        monkeypatch.setattr(vl.VectorEditSession, "commit_changes", boom)
        committed, blocked = controller.flush_edit_sessions()
        assert committed == 0
        assert any("回滚" in msg for msg in blocked)
