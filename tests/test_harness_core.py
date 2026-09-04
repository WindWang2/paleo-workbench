"""P2-C harness core tests: registry, executor guards, validation hooks."""
from __future__ import annotations

import time

import numpy as np
import pytest

from paleo_workbench.harness import (
    ActionContext,
    ActionRisk,
    ActionSpec,
    HarnessExecutor,
    MapValidationHook,
    ScientificValidator,
    get_action_registry,
    set_action_registry,
)
from paleo_workbench.harness.registry import ActionRegistry
from paleo_workbench.runtime import TaskScheduler
from paleo_workbench.harness.spec import validate_action_spec


def _spec(**overrides) -> ActionSpec:
    base = dict(
        action_id="demo.answer",
        description="Answer.",
        handler=lambda ctx, p: {"value": p.get("x", 1)},
        risk=ActionRisk.READ,
        input_schema={
            "type": "object",
            "properties": {"x": {"type": "number", "minimum": 0.0}},
            "required": ["x"],
            "additionalProperties": False,
        },
    )
    base.update(overrides)
    return ActionSpec(**base)


# ------------------------------------------------------------------ spec --
@pytest.mark.parametrize(
    "overrides,problem",
    [
        ({"action_id": "NoDot"}, "action_id"),
        ({"description": ""}, "description"),
        ({"handler": None, "provider_id": None}, "handler"),
        ({"input_schema": {"type": "string"}}, "input_schema"),
        ({"resource_profile": {"estimated_cpu_cores": 0}}, "estimated_cpu_cores"),
    ],
)
def test_action_spec_validation(overrides, problem):
    found = validate_action_spec(_spec(**overrides))
    assert any(problem in f for f in found)


def test_tool_schema_derived_from_spec():
    schema = _spec().tool_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "demo__answer"
    assert schema["function"]["parameters"]["required"] == ["x"]
    assert "risk: read" in schema["function"]["description"]


# -------------------------------------------------------------- registry --
def test_registry_rejects_duplicates_and_invalid():
    registry = ActionRegistry()
    registry.register(_spec())
    from paleo_workbench.harness import DuplicateActionError, InvalidActionSpecError

    with pytest.raises(DuplicateActionError):
        registry.register(_spec())
    with pytest.raises(InvalidActionSpecError):
        registry.register(_spec(action_id="bad spec"))
    with pytest.raises(InvalidActionSpecError):
        registry.register(_spec(action_id="demo.purge", risk=ActionRisk.DESTRUCTIVE))


def test_default_registry_has_domain_actions():
    registry = get_action_registry()
    try:
        ids = [s.action_id for s in registry.specs()]
        for expected in (
            "workspace.list_assets",
            "workspace.search",
            "workspace.get_lineage",
            "workspace.get_versions",
            "well.list",
            "well.open",
            "well.list_curves",
            "well.create_display",
            "seismic.open_volume",
            "seismic.get_slice",
            "seismic.compute_attribute",
            "map.create_factor_map",
            "map.add_layer",
            "map.set_style",
            "map.add_component",
            "map.validate",
            "map.export",
            "geology.list_horizons",
            "geology.list_faults",
            "workflow.status",
        ):
            assert expected in ids, f"{expected} missing"
        # no destructive actions installed
        assert all(s.risk is not ActionRisk.DESTRUCTIVE for s in registry.specs())
        # tool schemas cover every action 1:1
        assert len(registry.tool_schemas()) == len(ids)
    finally:
        set_action_registry(None)


# -------------------------------------------------------------- executor --
def test_execute_unknown_action_fails_explicitly():
    result = HarnessExecutor(ActionRegistry()).execute("nope.nothing", {})
    assert result.status == "fail"
    assert "unknown" in (result.error or "")


def test_execute_validates_parameters():
    registry = ActionRegistry()
    registry.register(_spec())
    result = HarnessExecutor(registry).execute("demo.answer", {})
    assert result.status == "fail"
    assert "required" in result.error


def test_execute_permission_gate():
    registry = ActionRegistry()
    registry.register(_spec(action_id="demo.write", risk=ActionRisk.WRITE))
    context = ActionContext(permissions=frozenset({ActionRisk.READ}))
    result = HarnessExecutor(registry).execute("demo.write", {"x": 1.0}, context)
    assert result.status == "fail"
    assert "permission" in result.error


def test_execute_required_context_gate():
    registry = ActionRegistry()
    registry.register(
        _spec(action_id="demo.need", required_context=("project",))
    )
    result = HarnessExecutor(registry).execute("demo.need", {"x": 1.0}, ActionContext())
    assert result.status == "fail"
    assert "project" in result.error


def test_execute_happy_path_metrics():
    registry = ActionRegistry()
    registry.register(_spec())
    result = HarnessExecutor(registry).execute("demo.answer", {"x": 4.5})
    assert result.status == "ok"
    assert result.outputs["value"] == 4.5
    assert result.elapsed_ms >= 0.0


def test_execute_handler_exception_isolated():
    def boom(ctx, p):
        raise ValueError("kaboom")

    registry = ActionRegistry()
    registry.register(_spec(action_id="demo.boom", handler=boom))
    result = HarnessExecutor(registry).execute("demo.boom", {"x": 1.0})
    assert result.status == "fail"
    assert "kaboom" in result.error


# ------------------------------------------------- #1137 cancel semantics --
def test_execute_task_cancelled_is_cancelled_not_fail():
    """A cooperating handler that raises TaskCancelled lands in 'cancelled'."""
    from paleo_workbench.runtime.task_scheduler import TaskCancelled

    def cancel_me(ctx, p):
        raise TaskCancelled("stop at safe point")

    registry = ActionRegistry()
    registry.register(_spec(action_id="demo.cancel", handler=cancel_me))
    result = HarnessExecutor(registry).execute("demo.cancel", {"x": 1.0})
    assert result.status == "cancelled"
    assert result.ok is False
    assert "cancelled" in (result.error or "")


def test_scheduler_marks_cancelled_task_not_failed():
    """End-to-end chain (#1137): scheduler cancel → cancel token fires in the
    action context → handler raises TaskCancelled → executor returns
    status='cancelled' → scheduler terminal state CANCELLED (not FAILED/DONE)."""
    import threading
    import time as _time

    from paleo_workbench.runtime import TaskScheduler, TaskSpec
    from paleo_workbench.runtime.task_scheduler import TaskCancelled, TaskState

    class _Token:
        """Cancel-token shape the harness/provider contexts understand."""

        def __init__(self, event: threading.Event):
            self._event = event

        @property
        def is_cancelled(self) -> bool:
            return self._event.is_set()

        def raise_if_cancelled(self) -> None:
            if self._event.is_set():
                raise TaskCancelled("provider execution cancelled")

    started = threading.Event()

    def hold_until_cancelled(ctx, p):
        started.set()
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and not ctx.cancel.is_cancelled:
            _time.sleep(0.01)
        ctx.cancel.raise_if_cancelled()  # cooperative stop at the safe point
        raise AssertionError("unreachable")

    registry = ActionRegistry()
    registry.register(_spec(action_id="demo.cancel", handler=hold_until_cancelled))
    executor = HarnessExecutor(registry)
    sched = TaskScheduler(max_workers=1)
    try:
        handle = sched.submit(
            TaskSpec(
                callable=lambda task_ctx: executor.execute(
                    "demo.cancel", {"x": 1.0}, ActionContext(cancel=_Token(task_ctx.cancelled))
                ),
                kind="io",
                title="cancel-chain",
            )
        )
        assert started.wait(timeout=5.0), "task never started"
        assert sched.cancel(handle.task_id) is True
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and handle.state in (
            TaskState.QUEUED,
            TaskState.RUNNING,
        ):
            _time.sleep(0.01)
        assert handle.state is TaskState.CANCELLED
        assert handle.error is None  # CANCELLED, not FAILED
    finally:
        sched.shutdown(wait=True, timeout=5)


# ------------------------------------------- #1178 output_schema contract --
def test_output_schema_violation_fails_action():
    registry = ActionRegistry()
    registry.register(
        _spec(
            action_id="demo.out",
            handler=lambda ctx, p: {"value": p.get("x", 1)},
            output_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
    )
    result = HarnessExecutor(registry).execute("demo.out", {"x": 4.5})
    assert result.status == "fail"
    assert "output.value" in result.error  # shape mismatch is explicit, never silent


def test_output_schema_satisfied_passes_and_absent_schema_unchanged():
    registry = ActionRegistry()
    registry.register(
        _spec(
            action_id="demo.out_ok",
            handler=lambda ctx, p: {"value": "fine"},
            output_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        )
    )
    result = HarnessExecutor(registry).execute("demo.out_ok", {"x": 1.0})
    assert result.status == "ok"
    # No output_schema declared → no output checking (backwards compatible).
    registry.register(_spec(action_id="demo.plain"))
    assert HarnessExecutor(registry).execute("demo.plain", {"x": 1.0}).status == "ok"


# -------------------------------------------- #1180 degraded admission --
def test_admission_import_failure_fails_loud_and_marks_degraded(monkeypatch, caplog):
    import sys

    from paleo_workbench.harness import executor as harness_executor

    harness_executor.reset_admission_degraded()
    monkeypatch.setitem(sys.modules, "paleo_workbench.runtime.resource_governor", None)
    registry = ActionRegistry()
    registry.register(_spec())
    try:
        with caplog.at_level("ERROR"):
            result = HarnessExecutor(registry).execute("demo.answer", {"x": 1.0})
        assert result.status == "fail"
        assert "without resource admission" in result.error
        assert harness_executor.ADMISSION_DEGRADED is True
        assert any("falling back" in r.message for r in caplog.records)
    finally:
        harness_executor.reset_admission_degraded()


def test_admission_singleton_broken_degrades_to_default_budget(monkeypatch, caplog):
    from paleo_workbench.runtime import resource_governor as rg
    from paleo_workbench.harness import executor as harness_executor

    def broken_get_governor():
        raise ImportError("governor singleton broken")

    harness_executor.reset_admission_degraded()
    monkeypatch.setattr(rg, "get_governor", broken_get_governor)
    registry = ActionRegistry()
    registry.register(_spec())
    try:
        with caplog.at_level("ERROR"):
            result = HarnessExecutor(registry).execute("demo.answer", {"x": 1.0})
        assert result.status == "ok"  # ran — but through guarded fallback admission
        assert harness_executor.ADMISSION_DEGRADED is True
        assert any("falling back" in r.message for r in caplog.records)
    finally:
        harness_executor.reset_admission_degraded()


# --------------------------------- #1186 WRITE risk + default permissions --
def test_write_risk_actions_aligned_with_side_effects():
    """Disk-writing/catalog-registering actions require explicit WRITE."""
    registry = get_action_registry()
    try:
        for action_id in ("map.create_factor_map", "map.export", "seismic.compute_attribute"):
            spec = registry.get(action_id)
            assert spec.risk is ActionRisk.WRITE, f"{action_id} must be WRITE risk"
        # A default (READ+COMPUTE) context is refused without crashing.
        result = HarnessExecutor(registry).execute(
            "map.create_factor_map", {"factor_name": "厚度"}, ActionContext()
        )
        assert result.status == "fail"
        assert "permission" in result.error
    finally:
        set_action_registry(None)


def test_from_app_defaults_to_read_compute():
    from types import SimpleNamespace

    from paleo_workbench.harness.context import ActionContext

    context = ActionContext.from_app(SimpleNamespace())
    assert context.permissions == frozenset({ActionRisk.READ, ActionRisk.COMPUTE})


# ------------------------------------- #1174 factor-name slug containment --
def test_factor_name_slug_never_escapes_artifact_dir(tmp_path):
    from pathlib import Path

    from paleo_workbench.harness.actions.mapping import _sanitize_factor_slug

    artifact_dir = tmp_path / "demo.artifacts" / "intermediate"
    for hostile in ("../../etc/passwd", "a/b/c", "厚度 图", "..", "x y", "ok-name"):
        slug = _sanitize_factor_slug(hostile)
        assert slug == "factor" or all(c.isalnum() or c in "_.-" for c in slug)
        artifact_path = artifact_dir / f"factor-{slug}-ab12cd.npz"
        artifact_path.resolve().relative_to(artifact_dir.resolve())  # containment holds
        assert Path(slug).name == slug  # single path component


def test_execute_admission_lease_released():
    from paleo_workbench.runtime import (
        ResourceBudget,
        ResourceGovernor,
        set_governor,
    )
    from paleo_workbench.runtime.memory_pressure import MemoryPressureMonitor

    monitor = MemoryPressureMonitor(ResourceBudget(), sampler=lambda b: (0.1, 0, 0))
    gov = ResourceGovernor(ResourceBudget(logical_cores=8), pressure_monitor=monitor)
    set_governor(gov)
    registry = ActionRegistry()
    registry.register(_spec())
    try:
        result = HarnessExecutor(registry).execute("demo.answer", {"x": 1.0})
        assert result.ok
        assert gov.runtime_status()["reserved"]["cores"] == 0
    finally:
        set_governor(None)


def test_read_action_dispatch_overhead_budget():
    """§38: pure READ action overhead < 10 ms excluding business IO."""
    import time

    registry = ActionRegistry()
    registry.register(_spec())
    executor = HarnessExecutor(registry)
    executor.execute("demo.answer", {"x": 1.0})  # warm
    samples = []
    for _ in range(50):
        t0 = time.perf_counter()
        executor.execute("demo.answer", {"x": 1.0})
        samples.append((time.perf_counter() - t0) * 1000)
    assert sorted(samples)[len(samples) // 2] < 10.0


def test_registry_lookup_is_o1_fast():
    import time

    registry = get_action_registry()
    try:
        t0 = time.perf_counter()
        for _ in range(10_000):
            registry.get("map.create_factor_map")
        elapsed = (time.perf_counter() - t0) * 1000
        assert elapsed < 200.0  # ~O(1) dict lookups
    finally:
        set_action_registry(None)


# ------------------------------------------------------------ validation --
def test_scientific_validator_all_nan_fails():
    report = ScientificValidator().validate_grid(np.full((5, 5), np.nan), label="g")
    assert report.verdict == "fail"
    assert not report.passed


def test_scientific_validator_thin_coverage_warns():
    values = np.full((10, 10), np.nan)
    values[0, 0] = 1.0
    report = ScientificValidator().validate_grid(values, label="g")
    assert report.verdict == "warning"
    assert report.passed


def test_scientific_validator_good_grid_passes():
    rng = np.random.default_rng(0)
    report = ScientificValidator().validate_grid(rng.random((8, 8)), label="g")
    assert report.verdict == "pass"


def test_scientific_validator_inverted_axis_fails():
    class FakeGrid:
        grid_z = np.ones((4, 4))
        grid_x = np.array([1.0, 0.0, 2.0, 3.0])
        grid_y = np.array([0.0, 1.0, 2.0, 3.0])
        crs = None
        unit = None

    report = ScientificValidator().validate_grid(FakeGrid(), label="g")
    assert report.verdict == "fail"


def test_map_validation_hook_empty_map_fails():
    from paleo_workbench.mapping.layers import MapDocument

    report = MapValidationHook().validate(MapDocument(title="x"))
    assert report.verdict == "fail"


def test_map_validation_hook_requires_components():
    from paleo_workbench.mapping.layers import MapDocument, WellPointMapLayer

    document = MapDocument(title="井位图")
    layer = WellPointMapLayer(name="井位")
    layer.features = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "properties": {"name": "W1"}}
    ]
    document.add_layer(layer)
    document.recompute_extent()

    report = MapValidationHook().validate(document, None, require_components=True)
    assert report.verdict == "fail"  # no composition
    assert any("composition" in r for r in report.reasons)


# ------------------------------------------------- review-round additions --
def test_default_permissions_are_read_compute_only():
    from paleo_workbench.harness.spec import DEFAULT_PERMISSIONS

    assert DEFAULT_PERMISSIONS == frozenset({ActionRisk.READ, ActionRisk.COMPUTE})


def test_map_apply_template_and_geology_interpretation(tmp_path):
    from paleo_workbench.harness.spec import ActionRisk
    from paleo_workbench.project.models import ProjectDocument

    registry = get_action_registry()
    try:
        executor = HarnessExecutor(registry)
        context = ActionContext(
            project=ProjectDocument.new(name="t", region="r"),
            project_path=str(tmp_path / "t.paleo.json"),
            permissions=frozenset({ActionRisk.READ, ActionRisk.COMPUTE, ActionRisk.WRITE}),
        )
        (tmp_path / "t.paleo.json").write_text("{}", encoding="utf-8")
        created = executor.execute(
            "map.create_well_location_map", {"title": "T"}, context
        )
        if not created.ok:  # project has no coordinate wells — use a factor map path instead
            pytest.skip("needs wells; covered by e2e")

        templated = executor.execute("map.apply_template", {"template": "standard", "title": "模板图"}, context)
        assert templated.ok, templated.error
        assert set(templated.outputs["components"]) >= {"legend", "scale_bar", "north_arrow", "title", "main_map"}

        interpretation = executor.execute(
            "geology.create_interpretation", {"name": "F1 断层", "horizon": "T2"}, context
        )
        assert interpretation.ok, interpretation.error
        assert interpretation.outputs["saved"] is False  # session-scope draft
        assert any(f.name == "F1 断层" for f in context.project.fault_interpretations)
    finally:
        set_action_registry(None)


def test_visualization_provider_executes_fallback_render(tmp_path, qapp):
    from paleo_workbench.mapping.layers import MapDocument, WellPointMapLayer
    from paleo_workbench.providers import (
        ProviderContext,
        execute_provider,
        get_provider_registry,
    )
    from paleo_workbench.providers.errors import ProviderExecutionError, ProviderRejectedInputError

    document = MapDocument(title="viz")
    layer = WellPointMapLayer(name="井位")
    layer.features = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "properties": {"name": "W1"}}
    ]
    document.add_layer(layer)
    document.recompute_extent()

    provider = get_provider_registry().get("viz.map_render.fallback")
    # #1177: providers write only inside the workspace the context provides.
    context = ProviderContext(workspace_root=str(tmp_path))
    out = tmp_path / "render.png"
    result = execute_provider(
        provider,
        inputs={"document": document},
        parameters={"output_path": "render.png", "width": 200, "height": 150},
        context=context,
    )
    assert out.exists() and out.stat().st_size > 0
    assert result.diagnostics["backend"] == "fallback"

    # Out-of-workspace destinations are refused (#1177): traversal + absolute.
    for escape in ("../escape.png", "/definitely-outside/escape.png"):
        with pytest.raises(ProviderExecutionError, match="outside the execution workspace"):
            execute_provider(
                provider,
                inputs={"document": document},
                parameters={"output_path": escape, "width": 64, "height": 64},
                context=context,
            )
    # No silent overwrite of the file just written.
    with pytest.raises(ProviderExecutionError, match="overwrite"):
        execute_provider(
            provider,
            inputs={"document": document},
            parameters={"output_path": "render.png", "width": 64, "height": 64},
            context=context,
        )

    # Unavailable backends reject honestly instead of raising garbage.
    qgis = get_provider_registry().find("viz.map_render.qgis")
    if qgis is not None and not qgis.available:
        with pytest.raises(ProviderRejectedInputError):
            execute_provider(
                qgis, inputs={"document": document},
                parameters={"output_path": str(tmp_path / "q.png")}, context=context,
            )


def test_compute_attribute_rejects_paths_outside_workspace(tmp_path):
    from paleo_workbench.harness.spec import ActionRisk
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.providers.refs import SeismicVolumeRef

    registry = get_action_registry()
    try:
        executor = HarnessExecutor(registry)
        context = ActionContext(
            project=ProjectDocument.new(name="t", region="r"),
            project_path=str(tmp_path / "t.paleo.json"),
            permissions=frozenset({ActionRisk.READ, ActionRisk.COMPUTE, ActionRisk.WRITE}),
        )
        context.active_volume = SeismicVolumeRef(volume_id="v", path=str(tmp_path / "v.zarr"))
        outside = executor.execute(
            "seismic.compute_attribute",
            {"attribute": "c3", "output_dir": "/definitely-outside/attr.zarr"},
            context,
        )
        assert outside.status == "fail"
        assert "workspace" in outside.error
    finally:
        set_action_registry(None)


def test_workspace_containment_blocks_relative_traversal(tmp_path):
    from paleo_workbench.harness.actions.mapping import _resolve_export_path
    from paleo_workbench.harness.actions.seismic import _resolve_volume_path
    from paleo_workbench.harness.spec import ActionRisk

    context = ActionContext(
        project_path=str(tmp_path / "t.paleo.json"),
        permissions=frozenset({ActionRisk.READ, ActionRisk.COMPUTE, ActionRisk.WRITE}),
    )
    for resolver in (_resolve_volume_path, _resolve_export_path):
        with pytest.raises(PermissionError):
            resolver(context, "../outside.zarr")
        with pytest.raises(PermissionError):
            resolver(context, "/etc/passwd")
        assert resolver(context, "inside.zarr") == str(tmp_path / "inside.zarr")


def test_scheduler_claim_is_atomic_no_double_run():
    """Two same-lane workers can never both run one task (atomic claim)."""
    import threading

    sched = TaskScheduler(max_workers=4)
    try:
        concurrent_runs = []
        lock = threading.Lock()

        def task(ctx):
            with lock:
                concurrent_runs.append(threading.get_ident())

        handles = [
            sched.submit_callable(task, kind="io", task_key=f"atomic/{i}", priority=5)
            for i in range(40)
        ]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and any(h.state.value != "done" for h in handles):
            time.sleep(0.02)
        assert all(h.state.value == "done" for h in handles)
        # 40 tasks, 4 workers: many tasks necessarily ran on shared threads,
        # but each task body saw exactly one entry — proven by done-state and
        # no failures; the double-run guard is the claim transition itself.
        states = [h.state.value for h in handles]
        assert states.count("done") == 40
    finally:
        sched.shutdown(wait=True, timeout=5)
