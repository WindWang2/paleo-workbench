"""Workstation UX V6 — UI context model + command applicability.

V6 §2/§4: the UI context layer is a *derived presentation state* fed by
authority adapters (providers); it never becomes a second master. Command
specs gain optional applicability metadata (context tags, stage scope,
WRITE requirement, reason-returning predicate); the registry evaluates
availability against a context snapshot without changing any legacy
behavior (no context → fully available, as today).
"""
from __future__ import annotations

import pytest

from paleo_workbench.ui.command_registry import (
    CommandAvailability,
    CommandRegistry,
    CommandSpec,
)
from paleo_workbench.ui.workstation.ui_context import (
    UIContextService,
    UIContextSnapshot,
)

pytestmark = pytest.mark.usefixtures("qapp")


# ---------------------------------------------------------------------------
# UIContextService — derived presentation context


def test_snapshot_defaults_are_honest_unknown():
    """No providers → explicit unknowns, never invented values."""
    service = UIContextService()
    snap = service.snapshot()
    assert isinstance(snap, UIContextSnapshot)
    assert snap.project_open is False
    assert snap.project_name is None
    assert snap.mapping_stage is None
    assert snap.active_layer_id is None
    assert snap.active_layer_editable is None  # unknown, not False
    assert snap.qgis_bridge_available is None  # unknown, not False
    assert snap.write_granted is False  # safe default: no grant
    assert snap.running_task_count == 0


def test_providers_feed_snapshot_fields():
    service = UIContextService()
    service.set_provider("project_open", lambda: True)
    service.set_provider("project_name", lambda: "Pearl River Mouth")
    service.set_provider("mapping_stage", lambda: "phase2")
    service.set_provider("write_granted", lambda: True)
    snap = service.snapshot()
    assert snap.project_open is True
    assert snap.project_name == "Pearl River Mouth"
    assert snap.mapping_stage == "phase2"
    assert snap.write_granted is True


def test_refresh_emits_context_changed_only_on_change(qtbot):
    service = UIContextService()
    calls: list[UIContextSnapshot] = []
    service.context_changed.connect(lambda snap: calls.append(snap))
    state = {"value": 1}

    service.set_provider("running_task_count", lambda: state["value"])
    service.refresh()
    assert len(calls) == 1
    assert calls[0].running_task_count == 1

    # Same value → no re-emit.
    service.refresh()
    assert len(calls) == 1

    # Changed value → emit.
    state["value"] = 3
    service.refresh()
    assert len(calls) == 2
    assert calls[1].running_task_count == 3


def test_provider_failure_fails_closed_to_unknown(qtbot):
    """A broken authority adapter degrades to honest unknown, never crashes."""

    def _boom():
        raise RuntimeError("backend gone")

    service = UIContextService()
    service.set_provider("mapping_stage", _boom)
    service.set_provider("project_open", lambda: True)
    snap = service.refresh()  # must not raise
    assert snap.mapping_stage is None
    assert snap.project_open is True


def test_clear_provider_restores_unknown():
    service = UIContextService()
    service.set_provider("project_name", lambda: "X")
    assert service.snapshot().project_name == "X"
    service.clear_provider("project_name")
    assert service.snapshot().project_name is None


# ---------------------------------------------------------------------------
# Command applicability


def _registry() -> CommandRegistry:
    return CommandRegistry()


def test_command_spec_applicability_fields_default_neutral():
    """Legacy specs (no applicability data) stay fully available."""
    spec = CommandSpec(id="core:x", label="X")
    assert spec.context_tags == ()
    assert spec.stages == ()
    assert spec.requires_write is False
    assert spec.hidden_when_unavailable is False
    assert spec.applicability is None


def test_evaluate_without_context_keeps_legacy_behavior():
    registry = _registry()
    registry.register(
        CommandSpec(
            id="map:edit.vertex",
            label="节点编辑",
            stages=("phase2",),
            requires_write=True,
            applicability=lambda ctx: "无活动图层",
        )
    )
    avail = registry.evaluate("map:edit.vertex", None)
    assert isinstance(avail, CommandAvailability)
    assert avail.enabled is True  # no context → no gating (legacy path)


def test_evaluate_write_gate_blocks_without_grant():
    registry = _registry()
    registry.register(
        CommandSpec(id="agent:export.map", label="导出地图", requires_write=True)
    )
    ctx = UIContextSnapshot(write_granted=False)
    avail = registry.evaluate("agent:export.map", ctx)
    assert avail.enabled is False
    assert "写入" in avail.reason


def test_evaluate_write_gate_allows_with_grant():
    registry = _registry()
    registry.register(
        CommandSpec(id="agent:export.map", label="导出地图", requires_write=True)
    )
    ctx = UIContextSnapshot(write_granted=True)
    assert registry.evaluate("agent:export.map", ctx).enabled is True


def test_evaluate_stage_scope_disables_with_reason():
    registry = _registry()
    registry.register(
        CommandSpec(id="map:add.provenance_line", label="物源线", stages=("phase2",))
    )
    in_stage = UIContextSnapshot(mapping_stage="phase2")
    other_stage = UIContextSnapshot(mapping_stage="phase1")
    assert registry.evaluate("map:add.provenance_line", in_stage).enabled is True
    avail = registry.evaluate("map:add.provenance_line", other_stage)
    assert avail.enabled is False
    assert avail.reason  # useful human reason, not empty


def test_evaluate_applicability_predicate_reason_wins_last():
    registry = _registry()
    registry.register(
        CommandSpec(
            id="map:toggle_editing",
            label="开始编辑",
            applicability=lambda ctx: (
                None if ctx.active_layer_editable else (ctx.active_layer_block_reason or "当前目标不可编辑")
            ),
        )
    )
    ok = UIContextSnapshot(active_layer_editable=True)
    raw = UIContextSnapshot(
        active_layer_editable=False, active_layer_block_reason="RAW 证据不可编辑"
    )
    assert registry.evaluate("map:toggle_editing", ok).enabled is True
    avail = registry.evaluate("map:toggle_editing", raw)
    assert avail.enabled is False
    assert avail.reason == "RAW 证据不可编辑"


def test_evaluate_unknown_command_reports_disabled():
    registry = _registry()
    avail = registry.evaluate("nope:nope", UIContextSnapshot())
    assert avail.enabled is False
    assert avail.reason


def test_find_reports_availability_without_dropping_disabled():
    """Disabled commands remain discoverable (with reason), hidden ones drop."""
    registry = _registry()
    registry.register(
        CommandSpec(id="map:a", label="阶段动作A", stages=("phase2",), context_tags=("mapping",))
    )
    registry.register(
        CommandSpec(
            id="map:b",
            label="阶段动作B",
            stages=("phase1",),
            hidden_when_unavailable=True,
        )
    )
    ctx = UIContextSnapshot(mapping_stage="phase2")
    results = registry.find("", context=ctx)
    ids = [s.id for s in results]
    assert "map:a" in ids  # available
    assert "map:b" not in ids  # hidden_when_unavailable
    avail = registry.evaluate("map:b", ctx)
    assert avail.enabled is False


def test_context_tags_boost_discovery_match():
    """Tag matching feeds the fuzzy haystack so 'mapping' queries find tagged commands."""
    registry = _registry()
    registry.register(
        CommandSpec(id="map:tagged", label="等值线", context_tags=("mapping", "contour"))
    )
    results = registry.find("mapping", context=UIContextSnapshot())
    assert any(s.id == "map:tagged" for s in results)


# ---------------------------------------------------------------------------
# Stage tool profile consumption (toolbar filtering source of truth)


def test_stage_tool_profile_filters_edit_actions():
    """StageToolProfile gains a predicate consumed by the composite toolbar."""
    from paleo_workbench.mapping_workspace.stages import MappingStage
    from paleo_workbench.mapping_workspace.stage_profiles import stage_profile

    phase1 = stage_profile(MappingStage.FACIES_CALIBRATION).tools
    phase2 = stage_profile(MappingStage.CONSTRAINT_FACTOR).tools
    # add_line 是阶段2的约束数字化入口，阶段1 不可用。
    assert phase2.allows_edit_action("add_line") is True
    assert phase1.allows_edit_action("add_line") is False
    # 所有阶段共有的编辑动作对两个阶段都可用。
    for action in ("add_polygon", "undo", "redo", "delete_selected"):
        assert phase1.allows_edit_action(action), action
        assert phase2.allows_edit_action(action), action
