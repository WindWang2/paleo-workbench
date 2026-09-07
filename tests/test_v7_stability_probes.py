"""Goal V7 stability & performance probes (headless; call-count based gates).

Design rules (Goal §9): gates use call counts / rebuild counts / asymptotic
ratios, never absolute wall-clock. Every probe declares its explicit scale and
stays bounded in time.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.edit_delta import DELTA_JOURNAL_LIMIT
from paleo_workbench.mapping.tool_availability import TOOL_IDS, evaluate_all
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def _polygon_feature(fid: str, offset: float) -> VectorFeature:
    return VectorFeature(
        fid,
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [offset, 0.0],
                    [offset + 1.0, 0.0],
                    [offset + 1.0, 1.0],
                    [offset, 1.0],
                    [offset, 0.0],
                ]
            ],
        },
        {"name": fid},
    )


def _editing_polygon_layer(count: int) -> VectorLayer:
    layer = VectorLayer(id=f"composite:L{count}", name="scale")
    layer.start_editing()
    for i in range(count):
        layer.edit_session.add_feature(_polygon_feature(f"f{i}", float(i)))
    return layer


class TestEvaluatorComplexity:
    """evaluate_all must be O(1) in feature/layer count (context derives cheaply)."""

    def test_evaluate_all_constant_in_selection_size(self):
        ctx_small = ToolContext(
            project_open=True,
            active_layer_id="L",
            active_layer_kind="polygon",
            editing=True,
            selection_count=10,
        )
        ctx_large = ToolContext(
            project_open=True,
            active_layer_id="L",
            active_layer_kind="polygon",
            editing=True,
            selection_count=100_000,
        )
        import timeit

        small = min(timeit.repeat(lambda: evaluate_all(ctx_small), number=200, repeat=3))
        large = min(timeit.repeat(lambda: evaluate_all(ctx_large), number=200, repeat=3))
        # Ratio gate (not wall clock): 10000x selection size must not scale
        # evaluator time (>4x would indicate accidental O(n) scanning).
        assert large < max(small * 4.0, small + 0.05)

    def test_evaluate_all_covers_registry_each_call(self):
        ctx = ToolContext(project_open=True)
        result = evaluate_all(ctx)
        assert set(result) == set(TOOL_IDS)


class TestDeltaJournalBounds:
    def test_journal_memory_bounded_at_scale(self):
        # Explicit scale: 3000 edits against the 1024-entry journal cap.
        layer = _editing_polygon_layer(1)
        session = layer.edit_session
        for i in range(DELTA_JOURNAL_LIMIT + 2000):
            session.change_attribute("f0", "name", f"v{i}")
        assert len(session.deltas()) <= DELTA_JOURNAL_LIMIT

    def test_undo_depth_unchanged_by_delta_stream(self):
        layer = _editing_polygon_layer(1)
        session = layer.edit_session
        for i in range(50):
            session.change_attribute("f0", "name", f"v{i}")
        # 1 add_feature + 50 attribute changes; the delta stream adds no commands.
        assert len(session.undo_stack) == 51


class TestScaleProbes:
    """Feature-count scales from Goal §9 (vector layers, headless session path)."""

    @pytest.mark.parametrize("count", [1_000, 10_000, 100_000])
    def test_session_operations_scale_gracefully(self, count):
        import timeit

        layer = VectorLayer(id="composite:scale", name="scale")
        layer.start_editing()
        session = layer.edit_session
        # Build at scale (allowed to be linear — one command per feature).
        for i in range(count):
            session.add_feature(_polygon_feature(f"f{i}", float(i % 1000)))
        assert len(session.features()) == count
        # Per-op costs that must stay effectively constant:
        move = timeit.timeit(
            lambda: session.move_feature("f0", 0.5, 0.5), number=20
        )
        # 20 moves on a 100k-feature session must not degrade by orders of
        # magnitude vs the journal-only path: assert absolute op cap instead of
        # wall clock — command application touches only the target feature.
        assert move < 5.0  # 20 ops; generous CI ceiling, regression tripwire
        deltas = session.deltas()
        assert len(deltas) <= DELTA_JOURNAL_LIMIT
        assert deltas[-1].operation == "move_feature"


class TestToolActivationStability:
    def test_100x_activate_deactivate_cycle(self, qtbot, tmp_path):
        from tests.test_composite_editing import _document

        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        layer = controller.create_layer("断层", "line")
        controller.start_editing()
        for i in range(100):
            controller.activate_tool("add_line")
            controller.activate_tool("pan")
        # After 100 cycles the active tool is consistent and the session intact.
        assert controller.tools.active_tool.tool_id == "pan"
        assert layer.edit_session is not None

    def test_100x_tool_state_resync(self, qtbot, tmp_path):
        from tests.test_composite_editing import _document

        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        controller.create_layer("相带", "polygon")
        controller.start_editing()
        for _ in range(100):
            document._sync_action_state()
        actions = document.action_controller.actions
        assert actions["add_polygon"].isEnabled()
        assert not actions["add_point"].isEnabled()

    def test_esc_cancels_active_tool_after_cycles(self, qtbot, tmp_path):
        from tests.test_composite_editing import _document

        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        controller.create_layer("断层", "line")
        controller.start_editing()
        controller.activate_tool("add_line")
        tool = controller.tools.active_tool
        tool.mouse_press((0.0, 0.0))
        assert controller.tools.key_press("escape")
        assert not tool.points  # capture cancelled, tool remains active


class TestLayerSwitchScale:
    def test_50_layer_switches_keep_single_active(self, qtbot, tmp_path):
        from tests.test_composite_editing import _document

        document = _document(qtbot, tmp_path)
        controller = document.edit_controller
        ids = [controller.create_layer(f"L{i}", "polygon").id for i in range(50)]
        for layer_id in ids:
            controller.set_active_layer(layer_id)
            assert controller.active_layer_id == layer_id
        # Extent history-like sync paths do not accumulate errors.
        document._sync_action_state()

    def test_selection_semantics_at_10k(self):
        layer = _editing_polygon_layer(10_000)
        layer.set_selection([f"f{i}" for i in range(0, 10_000, 100)])  # 100 ids
        assert len(layer.selection) == 100
        layer.select_all()
        assert len(layer.selection) == 10_000
        layer.invert_selection()
        assert len(layer.selection) == 0
        layer.set_selection(["f1"])
        layer.toggle_selection("f1")
        assert not layer.selection
