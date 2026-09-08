"""Goal V7 authoring-kernel contract tests (pure, headless — no Qt, no bridge)."""

from __future__ import annotations

import json

import pytest

from tests.qgis_support import QGIS_SKIP_REASON, qgis_bridge_available

from paleo_workbench.mapping.capability_model import (
    BRIDGE_BUILD_HINT,
    CapabilityFlag,
    LayerCapabilitySnapshot,
    QgisCapabilitySnapshot,
    layer_capability_snapshot,
    probe_qgis_capability,
    snapshot_stable_hash,
)
from paleo_workbench.mapping.edit_delta import (
    DELTA_JOURNAL_LIMIT,
    EditDelta,
    delta_from_command,
    geometry_hash,
)
from paleo_workbench.mapping.tool_availability import (
    TOOL_IDS,
    ToolAvailability,
    evaluate_all,
    evaluate_tool,
)
from paleo_workbench.mapping.tool_context import ToolContext, build_tool_context
from paleo_workbench.mapping.vector_layer import (
    AddFeatureCommand,
    ChangeAttributeCommand,
    MergeFeaturesCommand,
    SplitFeatureCommand,
    VectorEditSession,
    VectorFeature,
    VectorLayer,
)

# ---------------------------------------------------------------------------
# Capability model
# ---------------------------------------------------------------------------


def _available_snapshot(**overrides) -> QgisCapabilitySnapshot:
    base = dict(
        status="available",
        bridge_version="0.3.0",
        qgis_version="4.2.0",
        native_tools=frozenset({"pan", "zoomIn", "zoomOut", "addPoint", "addLine", "addPolygon", "vertex", "move", "select", "identify", "measure", "reshape"}),
        geometry_ops=frozenset({"union", "split_by_line", "make_valid", "is_valid", "validate", "reshape"}),
        dialogs=frozenset({"layer_properties", "renderer_properties"}),
        features=frozenset({"snapping_push", "layer_tree", "selection_highlight", "edit_indicator"}),
    )
    base.update(overrides)
    return QgisCapabilitySnapshot(**base)


class TestQgisCapabilitySnapshot:
    def test_unavailable_bridge_reports_build_hint(self):
        # Simulate a host without the bridge via the probe's importer hook
        # (no sys.modules surgery: None-entries and builtins.__import__
        # patches both poison the Windows extension-loader state for later
        # tests sharing the process).
        def _missing():
            raise ImportError("No module named 'qgis_render_bridge'")

        snapshot = probe_qgis_capability(_import_bridge=_missing)
        assert snapshot.status == "unavailable"
        assert "qgis_render_bridge" in snapshot.reason
        assert not snapshot.available

    @pytest.mark.skipif(not qgis_bridge_available(), reason=QGIS_SKIP_REASON)
    def test_available_bridge_probe_matches_manifest(self):
        # On hosts WITH the bridge (this venv after the V7 build), the probe
        # derives the snapshot from the compiled manifest. Runs in a fresh
        # subprocess: the Windows extension-loader state is process-global
        # (MSVCP/CRT squatting, DLL search order), so same-process sequencing
        # with bridge-absent simulations is inherently order-dependent.
        import json
        import subprocess
        import sys

        code = (
            "import json, sys; sys.path.insert(0, '.'); "
            "from paleo_workbench.mapping.capability_model import probe_qgis_capability; "
            "import qgis_render_bridge as bridge; "
            "s = probe_qgis_capability(); "
            "print(json.dumps({'status': s.status, "
            "'tools': sorted(s.native_tools), "
            "'manifest': sorted(bridge.capability_manifest()['native_tools'])}))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        assert data["status"] == "available"
        assert data["tools"] == data["manifest"]

    def test_available_flag_invariants(self):
        with pytest.raises(ValueError):
            CapabilityFlag(True, "reason on available")
        with pytest.raises(ValueError):
            QgisCapabilitySnapshot(status="available", reason="x")

    def test_feature_probes(self):
        snap = _available_snapshot()
        assert snap.feature("snapping_push").available
        assert not snap.feature("does_not_exist").available
        unavailable = QgisCapabilitySnapshot(status="unavailable", reason=BRIDGE_BUILD_HINT)
        assert unavailable.feature("snapping_push") == CapabilityFlag(False, BRIDGE_BUILD_HINT)

    def test_capability_flags_synthesis(self):
        snap = _available_snapshot()
        flags = snap.capability_flags()
        assert "qgis.snapping_push" in flags
        assert "qgis.native_tool.measure" in flags
        assert "qgis.geometry_op.reshape" in flags
        # Unavailable bridges synthesize nothing.
        empty = QgisCapabilitySnapshot(status="unavailable").capability_flags()
        assert empty == frozenset()

    def test_stable_hash(self):
        a = snapshot_stable_hash(_available_snapshot())
        b = snapshot_stable_hash(_available_snapshot())
        assert a == b and len(a) == 12
        other = snapshot_stable_hash(_available_snapshot(native_tools=frozenset({"pan"})))
        assert other != a

    def test_probe_degrades_on_old_bridge(self):
        import types

        fake = types.ModuleType("qgis_render_bridge")
        fake.__version__ = "0.2.17a0"  # no capability_manifest attr
        snap = probe_qgis_capability(_import_bridge=lambda: fake)
        assert snap.status == "degraded"
        assert "capability_manifest" in snap.reason

class TestLayerCapabilitySnapshot:
    def _layer(self):
        return VectorLayer(id="composite:L1", name="相带", kind_hint=None) if False else VectorLayer(id="composite:L1", name="相带")

    def test_full_open_layer(self):
        snap = layer_capability_snapshot(self._layer(), kind="polygon", qgis=_available_snapshot())
        for name in (
            "can_identify", "can_select", "can_edit", "can_add_feature", "can_delete_feature",
            "can_change_geometry", "can_change_attributes", "can_split", "can_merge",
            "can_snap", "can_topology", "can_open_properties", "can_symbol_edit",
        ):
            assert snap.capability(name).available, name
        assert snap.to_dict()["capabilities"]["can_edit"] is True

    def test_raw_locked_layer_blocks_edits_not_inspection(self):
        snap = LayerCapabilitySnapshot(layer_id="L", gate_allowed=False, gate_reason="RAW 图层不可变")
        assert snap.capability("can_identify").available
        assert not snap.capability("can_edit").available
        assert "RAW" in snap.capability("can_edit").unavailable_reason

    def test_non_writable_layer(self):
        snap = LayerCapabilitySnapshot(layer_id="L", writable=False)
        assert not snap.capability("can_add_feature").available
        assert snap.capability("can_select").available

    def test_unknown_capability_is_honest(self):
        snap = LayerCapabilitySnapshot(layer_id="L")
        flag = snap.capability("can_teleport")
        assert not flag.available
        assert "未知图层能力" in flag.unavailable_reason


# ---------------------------------------------------------------------------
# ToolContext
# ---------------------------------------------------------------------------


class TestToolContext:
    def test_build_from_controller_state(self):
        ctx = build_tool_context(
            controller_state={
                "active_layer_id": "composite:L1",
                "active_layer_kind": "polygon",
                "editing": True,
                "dirty": True,
                "selection_count": 2,
                "can_undo": True,
                "current_tool": "add_polygon",
            },
            qgis=_available_snapshot(),
            native_canvas_available=True,
        )
        assert ctx.active_layer_kind == "polygon"
        assert ctx.editing and ctx.dirty
        assert ctx.native_canvas_available
        assert "qgis.native_tool.addPolygon" in ctx.capability_flags
        assert ctx.qgis_available

    def test_empty_context_defaults(self):
        ctx = build_tool_context(controller_state=None)
        assert ctx.current_tool == "pan"
        assert not ctx.editing
        assert ctx.edit_gate_open  # default allows (no gate injected)
        assert ctx.contract_version == 2  # V8 M1 canonical contract

    def test_to_dict_serializable(self):
        ctx = build_tool_context(controller_state={"active_layer_id": "L"})
        data = ctx.to_dict()
        json.dumps(data)  # must not raise
        assert data["selection_geometry_types"] == []


# ---------------------------------------------------------------------------
# Availability matrix
# ---------------------------------------------------------------------------


def _ctx(**overrides) -> ToolContext:
    base = dict(
        project_open=True,
        active_layer_id="composite:L1",
        active_layer_kind="polygon",
        vector_writable=True,
        qgis_available=True,
        native_canvas_available=False,  # fallback canvas by default
        editing=True,
        dirty=True,
        current_tool="pan",
    )
    base.update(overrides)
    return ToolContext(**base)


class TestAvailabilityInvariants:
    def test_every_tool_has_reason_when_disabled(self):
        for tool_id in TOOL_IDS:
            av = evaluate_tool(tool_id, ToolContext())
            if not av.enabled:
                assert av.disabled_reason, f"{tool_id} disabled without reason"
            if not av.visible:
                assert not av.enabled

    def test_unknown_tool_fails_honest(self):
        av = evaluate_tool("warp_drive", ToolContext())
        assert not av.visible and not av.enabled
        assert "未知工具" in av.disabled_reason

    def test_enabled_tool_cannot_carry_reason(self):
        with pytest.raises(ValueError):
            ToolAvailability(tool_id="pan", enabled=True, disabled_reason="x")


class TestNavigation:
    def test_no_project_blocks_navigation(self):
        ctx = ToolContext(project_open=False)
        for tool_id in ("pan", "zoom_in", "full_extent", "refresh"):
            av = evaluate_tool(tool_id, ctx)
            assert not av.enabled
            assert "工程" in av.disabled_reason

    def test_extent_history_gates(self):
        av = evaluate_tool("previous_extent", _ctx(can_previous_extent=False))
        assert not av.enabled and "上一视图" in av.disabled_reason
        assert evaluate_tool("next_extent", _ctx(can_next_extent=True)).enabled


class TestInspection:
    def test_requires_layer(self):
        for tool_id in ("identify", "select", "select_rectangle", "clear_selection", "select_all", "invert_selection"):
            av = evaluate_tool(tool_id, _ctx(active_layer_id=""))
            assert not av.enabled
            assert "矢量图层" in av.disabled_reason

    def test_clear_selection_needs_selection(self):
        av = evaluate_tool("clear_selection", _ctx(selection_count=0))
        assert not av.enabled and "选中" in av.disabled_reason
        assert evaluate_tool("clear_selection", _ctx(selection_count=1)).enabled

    def test_select_all_needs_no_selection(self):
        assert evaluate_tool("select_all", _ctx(selection_count=0)).enabled

    def test_native_measure_always_executable(self):
        # measure 在原生画布上有双执行体（PwbMeasureTool 或视口路由），
        # evaluator 不做能力门（P1-1：禁用会让旧桥用户失去测距，
        # 而 fallback 路由在原生画布上依然接得到输入）。
        assert evaluate_tool("measure_distance", _ctx(native_canvas_available=True)).enabled
        assert evaluate_tool("measure_distance", _ctx()).enabled

    def test_degraded_bridge_keeps_legacy_tool_surface(self):
        import types

        fake = types.ModuleType("qgis_render_bridge")
        fake.__version__ = "0.2.17a0"  # pre-manifest bridge
        snap = probe_qgis_capability(_import_bridge=lambda: fake)
        assert snap.status == "degraded"
        # 可验证的 M3/M4 基线能力保持可用（存量安装不因升级变只读，P1-2）；
        # V7 新能力（measure/reshape/endpoint）诚实缺席。
        assert "addPoint" in snap.native_tools
        assert "measure" not in snap.native_tools
        assert "reshape" not in snap.geometry_ops
        assert "qgis.native_tool.addPoint" in snap.capability_flags()
        assert "qgis.native_tool.measure" not in snap.capability_flags()


class TestEditSession:
    def test_toggle_editing_gates(self):
        assert evaluate_tool("toggle_editing", _ctx(editing=False)).enabled
        # V8 canonical：锁分类事实（raw_locked/stage_locked）只在宿主门禁
        # 结论 edit_gate_open=False 时作为 fallback 判词。
        raw = evaluate_tool(
            "toggle_editing", _ctx(edit_gate_open=False, raw_locked=True))
        assert not raw.enabled and "RAW" in raw.disabled_reason
        stage = evaluate_tool(
            "toggle_editing", _ctx(edit_gate_open=False, stage_locked=True))
        assert not stage.enabled and "锁定" in stage.disabled_reason
        gate = evaluate_tool("toggle_editing", _ctx(edit_gate_open=False, edit_gate_reason="证据组锁定"))
        assert not gate.enabled and "证据组" in gate.disabled_reason
        unknown = evaluate_tool("toggle_editing", _ctx(edit_gate_open=None))
        assert not unknown.enabled and "未知" in unknown.disabled_reason
        assert not evaluate_tool("toggle_editing", _ctx(vector_writable=False)).enabled

    def test_save_edits_requires_dirty(self):
        av = evaluate_tool("save_edits", _ctx(dirty=False))
        assert not av.enabled and "未保存的修改" in av.disabled_reason
        assert evaluate_tool("save_edits", _ctx(dirty=True)).enabled
        not_editing = evaluate_tool("save_edits", _ctx(editing=False, dirty=True))
        assert not not_editing.enabled and "编辑" in not_editing.disabled_reason

    def test_rollback_mirrors_save(self):
        assert not evaluate_tool("rollback", _ctx(dirty=False)).enabled
        assert evaluate_tool("rollback", _ctx(dirty=True)).enabled

    def test_cancel_always_available(self):
        assert evaluate_tool("cancel", ToolContext()).enabled


class TestCapture:
    def test_requires_editing_session(self):
        av = evaluate_tool("add_polygon", _ctx(editing=False))
        assert not av.enabled and "编辑" in av.disabled_reason

    def test_kind_match_enforced(self):
        mismatch = evaluate_tool("add_point", _ctx(active_layer_kind="polygon"))
        assert not mismatch.enabled and "点图层" in mismatch.disabled_reason
        assert evaluate_tool("add_polygon", _ctx(active_layer_kind="polygon")).enabled

    def test_native_canvas_requires_manifest_tool(self):
        ctx = _ctx(native_canvas_available=True, active_layer_kind="point")
        av = evaluate_tool("add_point", ctx)
        assert not av.enabled and "采点" in av.disabled_reason
        flags = frozenset({"qgis.native_tool.addPoint"})
        assert evaluate_tool("add_point", _ctx(native_canvas_available=True, active_layer_kind="point", capability_flags=flags)).enabled

    def test_stage_profile_hides(self):
        # V8 canonical：阶段过滤由 mapping_stage 经 StageToolProfile 单点
        # 推导（hidden_by_stage_profile 已删除）——phase1 隐藏 add_line。
        ctx = _ctx(mapping_stage="facies_calibration")
        av = evaluate_tool("add_line", ctx)
        assert not av.visible and "阶段" in av.disabled_reason
        assert evaluate_tool("add_polygon", ctx).visible


class TestGeometryCommands:
    def test_move_vertex_need_editing_layer(self):
        assert evaluate_tool("move_feature", _ctx()).enabled
        assert evaluate_tool("vertex", _ctx()).enabled
        assert not evaluate_tool("move_feature", _ctx(editing=False)).enabled

    def test_delete_needs_selection(self):
        av = evaluate_tool("delete_selected", _ctx(selection_count=0))
        assert not av.enabled and "选中" in av.disabled_reason
        assert evaluate_tool("delete_selected", _ctx(selection_count=1)).enabled

    def test_split_needs_ready_inputs(self):
        av = evaluate_tool("split", _ctx(split_ready=False))
        assert not av.enabled and "切割线" in av.disabled_reason
        assert evaluate_tool("split", _ctx(split_ready=True)).enabled

    def test_merge_needs_two_polygons(self):
        av = evaluate_tool("merge", _ctx(merge_ready=False, compatible_polygon_count=1))
        assert not av.enabled and "两个" in av.disabled_reason
        assert evaluate_tool("merge", _ctx(merge_ready=True)).enabled

    def test_reshape_native_only(self):
        no_sel = evaluate_tool("reshape", _ctx(selection_count=0))
        assert not no_sel.enabled
        # P1-3：fallback 画布无输入路径（ReshapeTool 无鼠标方法），必须禁用
        # 且该原因是画布层面最根本的阻断。
        fallback = evaluate_tool("reshape", _ctx(selection_count=1))
        assert not fallback.enabled and "原生 QGIS 画布" in fallback.disabled_reason
        wrong_kind = evaluate_tool(
            "reshape", _ctx(native_canvas_available=True, active_layer_kind="point", selection_count=1)
        )
        assert not wrong_kind.enabled and "线/面" in wrong_kind.disabled_reason
        native = _ctx(native_canvas_available=True, selection_count=1)
        no_native = evaluate_tool("reshape", native)
        assert not no_native.enabled and "原生" in no_native.disabled_reason
        # 只有 addLine 数字化器、没有 reshape 算子 → 仍禁用（算法子）
        flags = frozenset({"qgis.native_tool.addLine"})
        av = evaluate_tool("reshape", _ctx(native_canvas_available=True, selection_count=1, capability_flags=flags))
        assert not av.enabled and "reshape" in av.disabled_reason
        flags = frozenset({"qgis.native_tool.addLine", "qgis.geometry_op.reshape"})
        assert evaluate_tool(
            "reshape",
            _ctx(native_canvas_available=True, selection_count=1, capability_flags=flags),
        ).enabled

    def test_repair_targets_polygons(self):
        av = evaluate_tool("repair_geometry", _ctx(active_layer_kind="line"))
        assert not av.enabled and "面图层" in av.disabled_reason
        assert evaluate_tool("repair_geometry", _ctx(active_layer_kind="polygon", editing=False)).enabled

    def test_undo_redo(self):
        assert not evaluate_tool("undo", _ctx(can_undo=False)).enabled
        assert evaluate_tool("undo", _ctx(can_undo=True)).enabled
        assert not evaluate_tool("redo", _ctx(can_redo=False)).enabled


class TestGisState:
    def test_snapping_topology_toggles(self):
        assert evaluate_tool("snapping", _ctx(snapping_enabled=False)).enabled
        av = evaluate_tool("snapping", _ctx(snapping_enabled=True))
        assert av.enabled and av.checked
        av = evaluate_tool("topology", _ctx(topology_enabled=True))
        assert av.checked
        bad_crs = evaluate_tool("topology", _ctx(crs_valid=False))
        assert not bad_crs.enabled and "CRS" in bad_crs.disabled_reason


class TestCheckedAndVisible:
    def test_current_tool_checked(self):
        av = evaluate_tool("vertex", _ctx(current_tool="vertex"))
        assert av.checked

    def test_toggle_editing_checked_while_editing(self):
        assert evaluate_tool("toggle_editing", _ctx(editing=True)).checked
        assert not evaluate_tool("toggle_editing", _ctx(editing=False)).checked

    def test_session_tools_visible_but_disabled_without_layer(self):
        # V8 M1（intentional）：无活动图层的会话工具可见 + 禁用，判词统一
        # 「没有活动的矢量图层」（旧 A-evaluator 的 invisible 行为已废弃）。
        for tool_id in ("add_point", "split", "save_edits", "undo"):
            av = evaluate_tool(tool_id, ToolContext(project_open=True))
            assert av.visible, tool_id
            assert not av.enabled, tool_id
            assert av.disabled_reason == "没有活动的矢量图层"

    def test_blocking_task_blocks_canvas_tools(self):
        ctx = _ctx(blocking_task="导出中")
        for tool_id in ("pan", "add_polygon", "vertex"):
            av = evaluate_tool(tool_id, ctx)
            assert not av.enabled and "导出中" in av.disabled_reason

    def test_evaluate_all_covers_registry(self):
        result = evaluate_all(_ctx())
        assert set(result) == set(TOOL_IDS)


# ---------------------------------------------------------------------------
# EditDelta
# ---------------------------------------------------------------------------


def _polygon_feature(fid: str = "f1") -> VectorFeature:
    return VectorFeature(
        fid,
        {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]},
        {"name": "A"},
    )


class TestEditDeltaSession:
    def _session(self) -> tuple[VectorLayer, VectorEditSession]:
        layer = VectorLayer(id="composite:L1", name="相带")
        layer.start_editing()
        return layer, layer.edit_session

    def test_add_feature_produces_create_delta(self):
        layer, session = self._session()
        session.qgis_capability_token = "abc123"
        with session.edit_source("add_polygon(native)"):
            session.add_feature(_polygon_feature())
        (delta,) = session.deltas()
        assert delta.operation == "create_feature"
        assert delta.source_tool == "add_polygon(native)"
        assert delta.qgis_capability == "abc123"
        assert delta.from_native_tool
        assert delta.before_geometry_hash is None
        assert delta.after_geometry["type"] == "Polygon"
        assert delta.order == 1
        assert delta.layer_id == "composite:L1"

    def test_default_source_is_command(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature())
        assert session.deltas()[0].source_tool == "command"
        assert not session.deltas()[0].from_native_tool

    def test_change_attribute_delta(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature("a1"))
        session.change_attribute("a1", "name", "B")
        delta = session.deltas()[-1]
        assert delta.operation == "update_attributes"
        assert delta.attribute_delta == {"name": ["A", "B"]}
        assert delta.after_geometry is None

    def test_split_and_merge_related_ids(self):
        layer, session = self._session()
        original = _polygon_feature("p1")
        session.add_feature(original)
        left = VectorFeature("s1", {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}, {})
        right = VectorFeature("s2", {"type": "Polygon", "coordinates": [[[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]]]}, {})
        session.split_feature("p1", [left, right])
        split_delta = session.deltas()[-1]
        assert split_delta.operation == "split_feature"
        assert split_delta.feature_id == "p1"
        assert set(split_delta.related_feature_ids) == {"s1", "s2"}

        merged = VectorFeature("m1", {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]}, {})
        session.merge_features(["s1", "s2"], merged)
        merge_delta = session.deltas()[-1]
        assert merge_delta.operation == "merge_features"
        assert merge_delta.feature_id == "m1"
        assert set(merge_delta.related_feature_ids) == {"s1", "s2"}

    def test_compound_flattens_to_constituent_deltas(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature("a1"))
        session.begin_edit_command()
        session.set_vertex("a1", (0, 1), (0.5, 0.5))
        session.set_vertex("a1", (0, 2), (0.5, 3.5))
        session.end_edit_command()
        deltas = [d for d in session.deltas() if d.operation == "move_vertex"]
        assert len(deltas) == 2
        assert [d.order for d in deltas] == [2, 3]

    def test_destroyed_compound_discards_deltas(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature("a1"))
        before = len(session.deltas())
        session.begin_edit_command()
        session.set_vertex("a1", (0, 1), (0.5, 0.5))
        session.destroy_edit_command()
        assert len(session.deltas()) == before

    def test_undo_produces_no_delta(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature())
        count = len(session.deltas())
        assert session.undo()
        assert len(session.deltas()) == count
        assert session.redo()
        assert len(session.deltas()) == count

    def test_rollback_clears_journal(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature())
        assert session.deltas()
        session.rollback_changes()
        assert not session.deltas()

    def test_selection_context_recorded(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature("a1"))
        session.add_feature(_polygon_feature("a2"))
        layer.set_selection(["a1"])
        session.move_feature("a2", 1.0, 1.0)
        delta = session.deltas()[-1]
        assert delta.operation == "move_feature"
        assert "a1" in delta.selection_context

    def test_order_tokens_monotonic_and_unique(self):
        layer, session = self._session()
        for i in range(5):
            session.add_feature(_polygon_feature(f"f{i}"))
        orders = [d.order for d in session.deltas()]
        assert orders == sorted(orders)
        assert len(set(orders)) == len(orders)

    def test_journal_is_bounded(self):
        layer, session = self._session()
        for i in range(DELTA_JOURNAL_LIMIT + 50):
            session.add_feature(_polygon_feature(f"f{i}"))
        assert len(session.deltas()) <= DELTA_JOURNAL_LIMIT

    def test_delta_serializes(self):
        layer, session = self._session()
        session.add_feature(_polygon_feature())
        data = session.deltas()[0].to_dict()
        json.dumps(data)
        assert data["operation"] == "create_feature"
        assert data["contract_version"] == 1


class TestEditDeltaPure:
    def test_geometry_hash_stable_and_null(self):
        geom = {"type": "Point", "coordinates": [1, 2]}
        assert geometry_hash(geom) == geometry_hash({"coordinates": (1, 2), "type": "Point"})
        assert geometry_hash(None) is None

    def test_unknown_operation_rejected(self):
        with pytest.raises(ValueError):
            EditDelta(layer_id="L", feature_id="f", operation="explode", session_id="s", order=1)

    def test_compound_command_has_no_direct_delta(self):
        from paleo_workbench.mapping.vector_layer import EditCommand

        assert delta_from_command(EditCommand("compound", {}, {}), layer_id="L", session_id="s", order=1, source_tool="x", qgis_capability="y") is None

    def test_command_type_coverage(self):
        # Every command class maps onto the normalized operation set.
        layer = VectorLayer(id="L", name="x")
        f = _polygon_feature("a")
        commands = [
            AddFeatureCommand(f),
            ChangeAttributeCommand(f, VectorFeature("a", f.geometry, {"n": "B"})),
        ]
        for command in commands:
            delta = delta_from_command(command, layer_id="L", session_id="s", order=1, source_tool="t", qgis_capability="u")
            assert delta is not None
        before = {"p": _polygon_feature("p")}
        after = {"p": None, "s1": _polygon_feature("s1")}
        assert delta_from_command(SplitFeatureCommand(before, after), layer_id="L", session_id="s", order=1, source_tool="t", qgis_capability="u").operation == "split_feature"
        m_before = {"x": _polygon_feature("x"), "y": _polygon_feature("y")}
        m_after = {"x": None, "y": None, "m": _polygon_feature("m")}
        assert delta_from_command(MergeFeaturesCommand(m_before, m_after), layer_id="L", session_id="s", order=1, source_tool="t", qgis_capability="u").operation == "merge_features"


class TestBlockingTaskGates:
    """Review-3 P1-2：后台任务进行中，全部画布/数据工具一致禁用。"""

    def test_blocking_task_blocks_everything_except_cancel(self):
        from paleo_workbench.mapping.tool_availability import TOOL_IDS

        # Gate order is coarse-to-fine: a kind mismatch (more fundamental)
        # still reports first. The blocking gate must fire for every tool
        # whose structural preconditions pass — assert per-tool accordingly.
        for tool_id in TOOL_IDS:
            ctx = _ctx(blocking_task="导出中")
            if tool_id in {"add_point", "add_line"}:
                ctx = _ctx(blocking_task="导出中", active_layer_kind="point" if tool_id == "add_point" else "line")
            av = evaluate_tool(tool_id, ctx)
            if tool_id == "cancel":
                assert av.enabled
            elif tool_id in {"add_point", "add_line", "add_polygon", "reshape", "repair_geometry",
                             "split", "merge", "delete_selected", "save_edits", "rollback",
                             "undo", "redo"}:
                # Data/shape gates may legitimately fire first on the
                # fixture context; the invariant is "disabled", reason
                # specificity is covered by the dedicated matrix tests.
                assert not av.enabled, tool_id
            else:
                assert not av.enabled, tool_id
                assert "导出中" in av.disabled_reason, tool_id

    def test_blocking_task_reason_fires_on_canvas_tools(self):
        for tool_id in ("pan", "zoom_in", "full_extent", "refresh",
                        "toggle_editing", "move_feature", "vertex"):
            av = evaluate_tool(tool_id, _ctx(blocking_task="导出中"))
            assert not av.enabled, tool_id
            assert "导出中" in av.disabled_reason, tool_id
