"""拓扑编辑迁移 M0 地基验收（规格 §8 → §6/§3）。

退出标准：场景 2（CRS 失配引导）、场景 15（停发窗口）通过；现有镜像
回归另由 test_mirror_* / test_v10_crs_chain_and_identity 保障（M0 不得
破坏 no-op 样式漂移自愈与显示序语义——见窗口外层照常自愈断言）。
"""
from __future__ import annotations

import json

from dataclasses import replace

import pytest

from paleo_workbench.mapping import qgis_mirror
from paleo_workbench.mapping.crs_chain import LayerCrsFacts, evaluate_edit_entry
from paleo_workbench.mapping.crs_contract import (
    coordinate_domain_mismatch,
    crs_coordinate_domain,
    infer_crs_from_extent,
)
from paleo_workbench.mapping.edit_session_set import (
    SESSION_SET,
    EditSessionSet,
    reset_session_set,
)
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
from paleo_workbench.mapping.qgis_mirror import (
    _MIRROR_LEDGER,
    _ledger_key,
    align_publish_ledger,
    mirror_snapshot_to_stack,
    reset_publish_ledger,
)
from paleo_workbench.project.domain import crs_domain_issues
from paleo_workbench.project.models import (
    CoordinateReference,
    ProjectDocument,
    UserVectorFeature,
    UserVectorLayer,
)


@pytest.fixture(autouse=True)
def _clean_m0_state():
    reset_publish_ledger()
    reset_session_set()
    yield
    reset_publish_ledger()
    reset_session_set()


# --------------------------------------------------------------------------- #
# §6 域校验 + 推断锁定（谓词层）
# --------------------------------------------------------------------------- #

def test_geographic_domain_is_degree_axes():
    assert crs_coordinate_domain("EPSG:4326") == (-180.0, -90.0, 180.0, 90.0)
    # 描述式拼写与未声明
    assert crs_coordinate_domain("EPSG:4326 / WGS84") == (-180.0, -90.0, 180.0, 90.0)
    assert crs_coordinate_domain("") is None


def test_domain_mismatch_local_data_under_geographic_declaration():
    mismatch = coordinate_domain_mismatch("EPSG:4326", (0.0, 0.0, 16000.0, 8000.0))
    assert mismatch is not None
    assert mismatch.crs == "EPSG:4326"
    assert "16000" in mismatch.describe()


def test_domain_mismatch_clear_cases():
    # 域内数据 / 空范围 / 未声明 CRS → 不失配（fail-open：只拦可证明的）
    assert coordinate_domain_mismatch("EPSG:4326", (100.0, 20.0, 120.0, 40.0)) is None
    assert coordinate_domain_mismatch("EPSG:4326", None) is None
    assert coordinate_domain_mismatch("", (0.0, 0.0, 16000.0, 8000.0)) is None
    # 投影 CRS：明显域外失配；可验证不了（伪造 id）→ None
    assert coordinate_domain_mismatch("EPSG:32650", (0.0, 0.0, 100.0, 100.0)) is not None
    assert coordinate_domain_mismatch("EPSG:99999", (0.0, 0.0, 100.0, 100.0)) is None


def test_inference_lock_semantics():
    # 超经纬度域 → 保持本地；域内 → 建议声明 4326；范围不可用 → 不推断
    assert infer_crs_from_extent((0.0, 0.0, 16000.0, 8000.0)).suggested_crs == ""
    geo = infer_crs_from_extent((100.0, 20.0, 120.0, 40.0))
    assert geo.suggested_crs == "EPSG:4326" and geo.suggests_declaration
    assert infer_crs_from_extent(None).suggested_crs == ""


def test_new_project_does_not_preset_geographic_crs():
    assert CoordinateReference().project_crs == ""
    assert ProjectDocument.new("M0").coordinate.project_crs == ""
    # 锁定字段：默认未锁定（首次导入推断用）
    assert CoordinateReference().crs_locked is False


# --------------------------------------------------------------------------- #
# 场景 2：CRS 失配引导（Given 工程声明 EPSG:4326 且数据本地坐标）
# --------------------------------------------------------------------------- #

_LOCAL_FACTS = [
    LayerCrsFacts("facies-draft", crs="", extent=(0.0, 0.0, 16000.0, 8000.0)),
    LayerCrsFacts("fault-lines", crs="", extent=(120.0, 30.0, 15800.0, 7900.0)),
]


def test_scenario2_entry_blocked_with_guidance_facts():
    """When 开始编辑 Then 阻止 + 引导（受影响层全景可见）。"""
    verdict = evaluate_edit_entry(
        [_LOCAL_FACTS[0]],
        canvas_crs="EPSG:4326",
        project_crs="EPSG:4326 / WGS84",
        all_layers=_LOCAL_FACTS,
        runtime_crs_capable=False,
    )
    assert not verdict.allowed
    assert verdict.mismatches, "域失配事实必须随判定供引导框呈现"
    assert "facies-draft" in verdict.reason and "fault-lines" in verdict.reason


def test_scenario2_one_click_fix_allows_entry_with_local_canvas():
    """一键修复（清除声明）后进入编辑且画布单位为本地（未声明帧）。"""
    verdict = evaluate_edit_entry(
        [_LOCAL_FACTS[0]],
        canvas_crs="EPSG:4326",
        project_crs="EPSG:4326 / WGS84",
        runtime_crs_capable=False,
    )
    assert not verdict.allowed
    fixed = evaluate_edit_entry(
        [_LOCAL_FACTS[0]],
        canvas_crs="",
        project_crs="",
        runtime_crs_capable=False,
    )
    assert fixed.allowed, "声明清除后：raw 本地帧，进前段放行"


def test_scenario2_document_level_guidance_flow(qtbot, tmp_path):
    """文档级：门被拒 → 一键清除声明（工程+工区+控制器同步）→ 复查放行。"""
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    project = ProjectDocument.new("M0 scenario2", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.coordinate.project_crs = "EPSG:4326 / WGS84"
    document = CompositeDocument(project)
    qtbot.addWidget(document)

    layer = document.edit_controller.create_layer("相带草稿", "polygon")
    from paleo_workbench.mapping.vector_layer import VectorFeature

    document.edit_controller.import_layer_features(layer.id, [VectorFeature(
        feature_id="f1",
        geometry={"type": "Polygon", "coordinates": [
            [[0.0, 0.0], [16000.0, 0.0], [16000.0, 8000.0], [0.0, 0.0]]]},
    )])
    # 构造器已绑定工程声明（edit_controller.project_crs ← 4326）。

    verdict, affected = document._crs_entry_gate(layer.id)
    assert not verdict.allowed
    assert [layer_id for layer_id, _name in affected] == [layer.id]

    document._clear_crs_declaration()
    assert project.coordinate.project_crs == ""
    assert project.workarea is None or project.workarea.project_crs == ""
    assert document.edit_controller.project_crs == ""

    verdict, affected = document._crs_entry_gate(layer.id)
    assert verdict.allowed and not affected


def test_guidance_dialog_clear_action(qtbot):
    from paleo_workbench.ui.crs_guidance import CrsGuidanceDialog

    verdict = evaluate_edit_entry(
        [_LOCAL_FACTS[0]],
        canvas_crs="EPSG:4326",
        project_crs="EPSG:4326 / WGS84",
        runtime_crs_capable=False,
    )
    dialog = CrsGuidanceDialog(verdict, affected_layers=[("facies-draft", "相带草稿")])
    qtbot.addWidget(dialog)
    assert not dialog.cleared
    dialog._clear_declaration()
    assert dialog.cleared  # 一键修复语义：调用方据此清除声明并重试进入编辑


def test_open_project_fallback_detection():
    """打开工程同一检测兜底旧工程（manager.load 消费 crs_domain_issues）。"""
    project = ProjectDocument.new("legacy")
    project.coordinate.project_crs = "EPSG:4326 / WGS84"
    project.user_vector_layers.append(UserVectorLayer(
        id="uv1", name="相带", geometry_kind="polygon",
        features=[UserVectorFeature(
            id="f1", geometry={"type": "Polygon", "coordinates": [
                [[0.0, 0.0], [16000.0, 0.0], [16000.0, 8000.0], [0.0, 0.0]]]},
            properties={})],
    ))
    issues = crs_domain_issues(project)
    assert len(issues) == 1 and "相带" in issues[0]
    # 声明清除后（一键修复过的工程）不再告警
    project.coordinate.project_crs = ""
    assert crs_domain_issues(project) == []


# --------------------------------------------------------------------------- #
# §3 会话集合管理器（单元）
# --------------------------------------------------------------------------- #

def test_session_set_lifecycle_and_growth():
    session = EditSessionSet()
    assert not session.is_open
    session.open("active", crs="", stack=object())
    assert session.is_open and session.contains("active")
    assert session.layer_ids() == ("active",)

    decisions = session.request_join(
        ["neighbor-ok", "neighbor-raw", "active"],
        gate=lambda layer_id: (
            (False, "RAW 保护——不可编辑") if layer_id == "neighbor-raw"
            else (True, "")),
    )
    accepted = {d.layer_id: d.accepted for d in decisions}
    assert accepted == {"neighbor-ok": True, "neighbor-raw": False, "active": True}
    rejected_reason = [d.reason for d in decisions if not d.accepted][0]
    assert "RAW" in rejected_reason  # 拒绝原因供状态条提示（场景 7 前置）
    assert session.layer_ids() == ("active", "neighbor-ok")  # 有序生长

    was = session.close()
    assert was == ("active", "neighbor-ok")
    assert not session.is_open


def test_session_set_freeze_and_mutex():
    session = EditSessionSet()
    assert session.allows_crs_change() == (True, "")
    assert session.allows_schema_change("any") == (True, "")
    session.open("draft-1", crs="EPSG:32650")
    assert session.frozen_crs == "EPSG:32650"
    allowed, reason = session.allows_crs_change()
    assert not allowed and "冻结" in reason
    allowed, reason = session.allows_schema_change("draft-1")
    assert not allowed and "保存" in reason
    assert session.allows_schema_change("outside") == (True, "")  # 集合外不受限


def test_session_set_window_is_stack_bound():
    stack_a, stack_b = object(), object()
    session = EditSessionSet()
    assert session.active_layer_ids(stack_a) == ()  # 未开会话
    session.open("draft-1", stack=stack_a)
    assert session.active_layer_ids(stack_a) == ("draft-1",)
    assert session.active_layer_ids(stack_b) == ()  # 绑定栈外不短路
    session.close()
    assert session.active_layer_ids(stack_a) == ()


# --------------------------------------------------------------------------- #
# 场景 15：停发窗口（镜像发布通道）
# --------------------------------------------------------------------------- #

class _WindowStack:
    """Delta 能力假栈：记录 upsert / 删除 / 顺序，支持样式读回与漂移注入。

    读回语义与真桥一致：upsert 应用下发的 renderer（读回值随之更新）；
    「外部改变」= 发布之间直接改 ``external_style``（no-op 发布的读回
    验证由此检出漂移 → 自愈重发）。
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.removed_except: list[list[str]] = []
        self.external_style: dict[str, str] = {}  # doc_id → 读回 renderer
        self.destination_pushes: list[str] = []

    def set_destination_crs(self, canvas, crs):
        self.destination_pushes.append(str(crs))

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta="",
                            fields_json="", min_scale=0.0, max_scale=0.0):
        self.calls.append({
            "doc_id": doc_id,
            "renderer": renderer_xml,
            "data_revision": data_revision,
            "delta": json.loads(delta) if delta else None,
            "features": json.loads(geojson)["features"],
        })
        self.external_style[doc_id] = renderer_xml
        return f"qgis-{doc_id}"

    def remove_mirror_layers_except(self, seen):
        self.removed_except.append(list(seen))

    def set_mirror_layer_order(self, order):
        pass

    def refresh_canvas(self, canvas):
        pass

    def mirror_style_json(self, doc_id):
        return json.dumps(
            {"exists": True, "renderer_xml": self.external_style.get(doc_id, "")})

    def calls_for(self, doc_id):
        return [call for call in self.calls if call["doc_id"] == doc_id]


def _window_layer(layer_id, features, revision=1, renderer="", style=None):
    style = style if style is not None else (
        {"qgis_style": {"renderer_xml": renderer}} if renderer else {})
    return MapLayerSnapshot(
        id=layer_id, name=layer_id, layer_type="vector",
        extent=(0.0, 0.0, 16000.0, 8000.0), crs="",
        data_revision=revision, style_revision=1,
        features=tuple(features), style=style, visible=True, opacity=1.0,
        renderer_payload=None,
    )


def _wfeature(fid, x=0.0, y=0.0):
    return {"id": fid, "geometry": {"type": "Point", "coordinates": [x, y]},
            "properties": {}}


class _Snap:
    def __init__(self, layers, project_crs=""):
        self.layers = tuple(layers)
        self.project_crs = project_crs


def test_scenario15_stop_publish_window():
    """Given A 层在编辑会话 When B 层（集合外）样式被外部改变
    Then B 重发/自愈照常，A 层数据不重发。"""
    stack = _WindowStack()
    renderer_b = '<renderer-v2 type="singleSymbol"><symbols/></renderer-v2>'
    layer_a = _window_layer("A", [_wfeature("a1"), _wfeature("a2")], revision=1)
    layer_b = _window_layer("B", [_wfeature("b1")], revision=1,
                            renderer=renderer_b)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_a, layer_b]))
    assert len(stack.calls_for("A")) == 1 and len(stack.calls_for("B")) == 1

    # A 进入编辑会话（集合 = {A}，绑定本发布栈）——停发窗口开启。
    SESSION_SET.open("A", crs="", stack=stack)
    assert SESSION_SET.active_layer_ids(stack) == ("A",)

    # A 数据变更（rev2 + 要素编辑）；B 样式被外部改变（宿主侧换渲染器）。
    edited_a = [_wfeature("a1"), _wfeature("a2", x=42.0)]
    layer_a2 = _window_layer("A", edited_a, revision=2)
    renderer_b2 = ('<renderer-v2 type="categorizedSymbol" attr="facies">'
                   "<symbols/></renderer-v2>")
    layer_b2 = _window_layer("B", [_wfeature("b1")], revision=1,
                             renderer=renderer_b2)
    diags: list[tuple[str, str]] = []
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_a2, layer_b2]),
                             diags=diags)

    # A：数据不重发（零 upsert），台账冻结在旧基线。
    assert stack.calls_for("A") == [stack.calls[0]]
    assert any("edit-window" in msg and doc == "A" for doc, msg in diags)
    entry_a = _MIRROR_LEDGER[_ledger_key(stack, "A")]
    assert entry_a.data_revision == 1, "编辑期数据台账冻结"
    assert not entry_a.authoritative

    # B（集合外）：样式变化照常重发。
    b_calls = stack.calls_for("B")
    assert len(b_calls) == 2 and b_calls[1]["renderer"] == renderer_b2


def test_scenario15_outside_set_style_drift_still_self_heals():
    """停发窗口外层照常发布（M0 分支版）。

    注：no-op 样式漂移**自愈**（读回验证 → 强制重发）属于在途 V10
    M-K 工作（未进本分支）——随该流合并后，本测试恢复漂移断言
    （见工作树版本 test_scenario15_outside_set_style_drift_still_self_heals）。
    分支上钉住的核心：集合外层的数据/样式变化照常重发、A 仍冻结。
    """
    stack = _WindowStack()
    layer_a = _window_layer("A", [_wfeature("a1")], revision=1)
    renderer = ('<renderer-v2 type="singleSymbol">'
                "<symbols><symbol name=\"0\"/></symbols></renderer-v2>")
    layer_b = _window_layer("B", [_wfeature("b1")], revision=1,
                            renderer=renderer)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_a, layer_b]))
    SESSION_SET.open("A", crs="", stack=stack)
    # B 样式变化（宿主侧换渲染器）→ 集合外照常重发。
    renderer2 = ('<renderer-v2 type="categorizedSymbol" attr="facies">'
                 "<symbols/></renderer-v2>")
    layer_b2 = _window_layer("B", [_wfeature("b1")], revision=1,
                             renderer=renderer2)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_a, layer_b2]))
    assert len(stack.calls_for("B")) == 2
    assert stack.calls_for("A") == [stack.calls[0]], "A 仍在停发窗口"



def test_ledger_alignment_after_commit_skips_republish():
    """§3 台账对齐：commit 后台账直跳新基线（镜像=真源），无需重发。"""
    stack = _WindowStack()
    features = [_wfeature("a1"), _wfeature("a2")]
    layer = _window_layer("A", features, revision=1)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    assert len(stack.calls_for("A")) == 1

    SESSION_SET.open("A", crs="", stack=stack)
    # 编辑发生（rev2：a2 移动）——窗口内不重发。
    layer_rev2 = _window_layer(
        "A", [_wfeature("a1"), _wfeature("a2", x=42.0)], revision=2)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_rev2]))
    assert len(stack.calls_for("A")) == 1

    # 提交：对齐台账到新基线（宿主已消费 committed* 增量的 M1 语义）。
    assert align_publish_ledger(stack, layer_rev2) is True
    entry = _MIRROR_LEDGER[_ledger_key(stack, "A")]
    assert entry.data_revision == 2
    assert entry.authoritative, "对齐后状态 = 镜像=真源"

    SESSION_SET.close()
    # 对齐生效的钉子：同 token 再发布 → 数据 no-op（token 公式与发布一致）。
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_rev2]))
    assert len(stack.calls_for("A")) == 1

    # 后续真实变更（rev3）恢复增量通道（基线 = 对齐后的 2）。
    layer_rev3 = _window_layer(
        "A", [_wfeature("a1"), _wfeature("a2", x=99.0)], revision=3)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_rev3]))
    calls = stack.calls_for("A")
    assert len(calls) == 2 and calls[1]["delta"] is not None
    assert calls[1]["delta"]["base_revision"] == 2


def test_align_requires_prior_publish_and_known_revision():
    stack = _WindowStack()
    layer = _window_layer("A", [_wfeature("a1")], revision=1)
    # 从未发布 → 对齐失败（镜像上没有数据，冻结成 no-op 会静默丢层）
    assert align_publish_ledger(stack, layer) is False
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    # 修订不可用（duck-typed 0）→ 对齐失败
    bare = replace(layer, data_revision=0)
    assert align_publish_ledger(stack, bare) is False


def test_window_close_resumes_normal_publish():
    stack = _WindowStack()
    layer = _window_layer("A", [_wfeature("a1"), _wfeature("a2")], revision=1)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    SESSION_SET.open("A", crs="", stack=stack)
    layer_rev2 = _window_layer(
        "A", [_wfeature("a1"), _wfeature("a2", x=5.0)], revision=2)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_rev2]))
    assert len(stack.calls_for("A")) == 1
    SESSION_SET.close()
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer_rev2]))
    # 窗口关闭：冻结的变更全部待发 → 恢复发布（delta，基线 1）
    calls = stack.calls_for("A")
    assert len(calls) == 2 and calls[1]["delta"]["base_revision"] == 1
