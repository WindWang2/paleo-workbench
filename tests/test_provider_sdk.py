"""P2-B provider SDK tests: contracts, registry, execution, built-ins."""
from __future__ import annotations

import threading
from typing import Any

import pytest

from paleo_workbench.providers import (
    DuplicateProviderError,
    InvalidParametersError,
    InvalidProviderError,
    PathRef,
    ProviderDescriptor,
    ProviderFamily,
    ProviderRegistry,
    ProviderRejectedInputError,
    ProviderResult,
    ResourceProfile,
    UnknownProviderError,
    execute_provider,
    get_provider_registry,
    set_provider_registry,
    validate_parameters,
)
from paleo_workbench.providers.base import ProviderContext


def _descriptor(**overrides: Any) -> ProviderDescriptor:
    base = dict(
        provider_id="test.echo",
        family=ProviderFamily.INTERPOLATION,
        version="1.0.0",
        display_name="Echo",
        input_types=("PathRef",),
        output_types=("PathRef",),
        parameters_schema={
            "type": "object",
            "properties": {
                "factor": {"type": "number", "minimum": 0.0, "maximum": 10.0},
                "mode": {"type": "string", "enum": ["a", "b"]},
                "count": {"type": "integer", "minimum": 1},
                "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "boom": {"type": "integer", "description": "测试钩子: 非 0 时抛异常"},
            },
            "required": ["factor"],
            "additionalProperties": False,
        },
        resource_profile=ResourceProfile(estimated_cpu_cores=1.0),
    )
    base.update(overrides)
    return ProviderDescriptor(**base)


class EchoProvider:
    def __init__(self, **overrides: Any):
        self._descriptor = _descriptor(**overrides)
        self.calls: list[tuple[dict, dict, ProviderContext]] = []

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def execute(self, inputs, parameters, context) -> ProviderResult:
        self.calls.append((dict(inputs), dict(parameters), context))
        if parameters.get("boom"):
            raise RuntimeError("boom")
        return ProviderResult(
            artifacts=[],
            diagnostics={"echo": parameters.get("factor")},
            metrics={"worked": True},
        )


class FakeCatalog:
    """CatalogPort-shaped recorder for provenance tests."""

    def __init__(self):
        self.runs: list[dict] = []
        self.lock = threading.Lock()
        self._next = 0

    def begin_run(self, *, operation, input_version_ids=None, parameters=None, generator_version=None, **kw):
        self._next += 1
        run = {
            "run_id": f"run-{self._next}",
            "operation": operation,
            "inputs": list(input_version_ids or []),
            "parameters": parameters,
            "generator": generator_version,
            "status": "running",
        }
        with self.lock:
            self.runs.append(run)
        from types import SimpleNamespace

        return SimpleNamespace(run_id=run["run_id"])

    def complete_run(self, run_id, *, status="complete"):
        with self.lock:
            for run in self.runs:
                if run["run_id"] == run_id:
                    run["status"] = status
        return run_id

    def register_output(self, *, run_id, name, path, **kw):
        return {"output": name, "path": path}

    def register_derived(self, *, run_id, name, path, **kw):
        return {"derived": name, "path": path}


# ------------------------------------------------------------ contracts --
@pytest.mark.parametrize(
    "overrides,problems",
    [
        ({"provider_id": "BAD ID"}, ["provider_id"]),
        ({"provider_id": ""}, ["provider_id"]),
        ({"version": "abc"}, ["version"]),
        ({"display_name": " "}, ["display_name"]),
        ({"parameters_schema": {"type": "array"}}, ["parameters_schema"]),
        ({"input_types": ("NotAType",)}, ["input_types"]),
        ({"threading_model": "sometimes"}, ["threading_model"]),
        (
            {"resource_profile": ResourceProfile(estimated_cpu_cores=0)},
            ["estimated_cpu_cores"],
        ),
    ],
)
def test_descriptor_validation_catches_structural_problems(overrides, problems):
    from paleo_workbench.providers import validate_descriptor

    found = validate_descriptor(_descriptor(**overrides))
    for problem in problems:
        assert any(problem in f for f in found), f"{problem} missing in {found}"


def test_descriptor_valid_when_well_formed():
    from paleo_workbench.providers import validate_descriptor

    assert validate_descriptor(_descriptor()) == []


def test_descriptor_serializes():
    data = _descriptor().to_dict()
    assert data["provider_id"] == "test.echo"
    assert data["family"] == "interpolation"
    assert data["resource_profile"]["estimated_cpu_cores"] == 1.0
    import json

    json.dumps(data)  # must be JSON-safe


# --------------------------------------------------------------- registry --
def test_registry_register_and_lookup():
    registry = ProviderRegistry()
    provider = EchoProvider()
    registry.register(provider)
    assert registry.get("test.echo") is provider
    assert registry.find("missing") is None
    with pytest.raises(UnknownProviderError):
        registry.get("missing")


def test_registry_duplicate_id_rejected():
    registry = ProviderRegistry()
    registry.register(EchoProvider())
    with pytest.raises(DuplicateProviderError):
        registry.register(EchoProvider())


def test_registry_same_id_replace_allowed():
    registry = ProviderRegistry()
    registry.register(EchoProvider())
    registry.register(EchoProvider(), replace=True)
    assert len(registry) == 1


def test_registry_invalid_provider_quarantined_not_installed():
    registry = ProviderRegistry()
    with pytest.raises(InvalidProviderError):
        registry.register(EchoProvider(provider_id="bad id"))
    assert registry.find("bad id") is None
    assert "bad id" in registry.quarantined()


def test_registry_version_conflict_quarantined():
    registry = ProviderRegistry()
    registry.register(EchoProvider(version="1.0.0"))
    with pytest.raises(DuplicateProviderError):
        registry.register(EchoProvider(version="2.0.0"))
    assert "version conflict" in registry.quarantined()["test.echo"]


def test_registry_by_family_and_descriptors_sorted():
    registry = ProviderRegistry()
    registry.register(EchoProvider(provider_id="test.zzz"))
    registry.register(
        EchoProvider(provider_id="test.aaa", family=ProviderFamily.SEISMIC_ATTRIBUTE)
    )
    interpolation = registry.by_family(ProviderFamily.INTERPOLATION)
    assert len(interpolation) == 1
    descriptors = registry.descriptors()
    keys = [(d.family.value, d.provider_id) for d in descriptors]
    assert keys == sorted(keys)


def test_provider_without_descriptor_rejected():
    registry = ProviderRegistry()

    class Naked:
        pass

    with pytest.raises(InvalidProviderError):
        registry.register(Naked())  # type: ignore[arg-type]


def test_builtin_providers_registered_on_default_registry():
    registry = get_provider_registry()
    try:
        ids = {d.provider_id for d in registry.descriptors()}
        assert "interpolation.kriging" in ids
        assert "interpolation.idw" in ids
        assert "seismic.attribute.c3" in ids
        assert "export.map_product" in ids
        assert "viz.map_render.fallback" in ids
        # onnxruntime present on this machine → the bridge registers; on
        # machines without it the factory is quarantined, not fatal.
        inference = [d for d in registry.descriptors(ProviderFamily.INFERENCE)]
        assert all(d.provider_id == "inference.tiled_onnx" for d in inference)
    finally:
        set_provider_registry(None)


def test_entry_point_discovery_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PALEO_PROVIDER_ENTRY_POINTS", raising=False)
    registry = ProviderRegistry()
    statuses = registry.load_entry_points()
    assert statuses.get("_disabled")


# ------------------------------------------------------------- validation --
def test_validate_parameters_subset_semantics():
    schema = _descriptor().parameters_schema
    assert validate_parameters(schema, {"factor": 1.5}) == []
    problems = validate_parameters(schema, {})
    assert any("required" in p for p in problems)
    problems = validate_parameters(schema, {"factor": 11.0})
    assert any("maximum" in p for p in problems)
    problems = validate_parameters(schema, {"factor": 1.0, "mode": "c"})
    assert any("enum" in p for p in problems)
    problems = validate_parameters(schema, {"factor": 1.0, "count": 2.5})
    assert any("count" in p for p in problems)
    problems = validate_parameters(schema, {"factor": 1.0, "tags": []})
    assert any("minItems" in p for p in problems)
    problems = validate_parameters(schema, {"factor": 1.0, "unknown": 1})
    assert any("additionalProperties" in p for p in problems)
    problems = validate_parameters(schema, {"factor": True})
    assert problems  # boolean is not a number in our subset


# ------------------------------------------- #1178 recursive validation --
NESTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "roi": {
            "type": "object",
            "properties": {
                "il0": {"type": "integer", "minimum": 0},
                "xl0": {"type": "integer", "enum": [0, 1, 2]},
            },
            "required": ["il0", "xl0"],
            "additionalProperties": False,
        },
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    "additionalProperties": False,
}


def test_nested_required_missing_rejected():
    problems = validate_parameters(NESTED_SCHEMA, {"roi": {"il0": 0}})
    assert any("roi.xl0: required" in p for p in problems)


def test_nested_additional_properties_false_rejected():
    problems = validate_parameters(
        NESTED_SCHEMA, {"roi": {"il0": 0, "xl0": 1, "surprise": True}}
    )
    assert any("roi.surprise" in p and "additionalProperties" in p for p in problems)


def test_legacy_schema_without_nested_additional_properties_still_allows_extras():
    # Backward compatibility: JSON Schema default is absent = allow.
    legacy = {
        "type": "object",
        "properties": {
            "roi": {"type": "object", "properties": {"il0": {"type": "integer"}}},
        },
    }
    assert validate_parameters(legacy, {"roi": {"il0": 1, "extra": "fine"}}) == []


def test_nested_enum_and_bounds_validated_recursively():
    problems = validate_parameters(NESTED_SCHEMA, {"roi": {"il0": -1, "xl0": 5}})
    assert any("roi.il0" in p and "minimum" in p for p in problems)
    assert any("roi.xl0" in p and "enum" in p for p in problems)


def test_array_items_object_required_validated():
    assert validate_parameters(NESTED_SCHEMA, {"features": [{"name": "a"}]}) == []
    problems = validate_parameters(NESTED_SCHEMA, {"features": [{"name": "a"}, {}]})
    assert any("features[1].name: required" in p for p in problems)


# ------------------------------------------- B3 union types / unknown types --
UNION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mode": {"type": ["string", "null"], "description": "optional string"},
        "count": {"type": ["integer", "string"]},
        "weird": {"type": ["mystery", "riddle"]},
        "odd": {"type": "mystery"},
    },
    "required": [],
    "additionalProperties": False,
}


def test_union_type_matches_any_member_and_null_legitimizes_none():
    assert validate_parameters(UNION_SCHEMA, {"mode": None, "count": "three"}) == []
    assert validate_parameters(UNION_SCHEMA, {"mode": "fast", "count": 3}) == []


def test_union_type_value_matching_no_member_is_rejected():
    problems = validate_parameters(UNION_SCHEMA, {"mode": 5})
    assert any("mode" in p and "expected one of" in p for p in problems)
    # None without "null" in the union matches no member.
    problems = validate_parameters(UNION_SCHEMA, {"count": None})
    assert any("count" in p for p in problems)
    # bool is not an integer even inside a union.
    problems = validate_parameters(UNION_SCHEMA, {"count": True})
    assert any("count" in p for p in problems)


def test_union_of_only_unknown_types_is_rejected_not_silently_passed():
    problems = validate_parameters(UNION_SCHEMA, {"weird": 1})
    assert any("weird" in p and "no known JSON type in union" in p for p in problems)


def test_single_unknown_type_string_is_rejected_not_silently_passed():
    problems = validate_parameters(UNION_SCHEMA, {"odd": 1})
    assert any("odd" in p and "unknown type" in p for p in problems)


# -------------------------------------------------------------- execution --
def test_execute_provider_happy_path_with_provenance():
    registry = ProviderRegistry()
    provider = EchoProvider()
    registry.register(provider)
    catalog = FakeCatalog()
    result = execute_provider(
        registry,
        "test.echo",
        inputs={"path": PathRef(path="/tmp/x")},
        parameters={"factor": 2.0},
        context=ProviderContext(catalog=catalog),
    )
    assert result.diagnostics["echo"] == 2.0
    assert result.metrics["elapsed_ms"] >= 0.0
    assert result.provenance["provider_id"] == "test.echo"
    assert result.provenance["provider_version"] == "1.0.0"
    assert result.provenance["parameters"] == {"factor": 2.0}
    assert len(catalog.runs) == 1
    assert catalog.runs[0]["status"] == "complete"
    assert catalog.runs[0]["generator"] == "1.0.0"


def test_execute_provider_rejects_invalid_parameters():
    registry = ProviderRegistry()
    registry.register(EchoProvider())
    with pytest.raises(InvalidParametersError):
        execute_provider(registry, "test.echo", parameters={"factor": 99.0})


def test_execute_provider_rejects_undeclared_input_type():
    registry = ProviderRegistry()
    provider = EchoProvider()
    registry.register(provider)
    with pytest.raises(ProviderRejectedInputError):
        execute_provider(
            registry, "test.echo", inputs={"path": "just-a-string"}, parameters={"factor": 1.0}
        )


def test_execute_provider_wraps_exceptions_and_fails_run():
    registry = ProviderRegistry()
    provider = EchoProvider()
    registry.register(provider)
    catalog = FakeCatalog()
    from paleo_workbench.providers import ProviderExecutionError

    with pytest.raises(ProviderExecutionError) as excinfo:
        execute_provider(
            registry,
            "test.echo",
            parameters={"factor": 1.0, "boom": 1},
            context=ProviderContext(catalog=catalog),
        )
    assert "boom" in str(excinfo.value)
    assert catalog.runs[0]["status"] == "failed"


def test_execute_provider_admits_through_governor():
    """The governor lease is taken and released around execution."""
    from paleo_workbench.runtime import ResourceBudget, ResourceGovernor
    from paleo_workbench.runtime.memory_pressure import MemoryPressureMonitor

    monitor = MemoryPressureMonitor(ResourceBudget(), sampler=lambda b: (0.1, 0, 0))
    gov = ResourceGovernor(ResourceBudget(logical_cores=8), pressure_monitor=monitor)
    from paleo_workbench.runtime import set_governor

    previous = get_provider_registry()
    set_provider_registry(None)
    registry = ProviderRegistry()
    registry.register(EchoProvider())
    set_governor(gov)
    try:
        result = execute_provider(registry, "test.echo", parameters={"factor": 1.0})
        assert result.metrics["worked"] is True
        reserved = gov.runtime_status()["reserved"]
        assert reserved["cores"] == 0  # lease released
        assert gov.metrics.admitted == 1
        assert gov.metrics.released == 1
    finally:
        from paleo_workbench.runtime import set_governor as sg

        class _Restore:
            pass

        sg(None)
        set_provider_registry(previous)


def test_execute_provider_pressure_shedding_surfaces():
    from paleo_workbench.runtime import (
        ResourceBudget,
        ResourceExhausted,
        ResourceGovernor,
        set_governor,
    )
    from paleo_workbench.runtime.memory_pressure import MemoryPressureMonitor, PressureState

    monitor = MemoryPressureMonitor(ResourceBudget(), sampler=lambda b: (0.99, 0, 0))
    monitor._state = PressureState.CRITICAL  # noqa: SLF001 — forced state
    gov = ResourceGovernor(ResourceBudget(logical_cores=8), pressure_monitor=monitor)
    registry = ProviderRegistry()
    registry.register(EchoProvider())
    set_governor(gov)
    try:
        with pytest.raises(ResourceExhausted) as excinfo:
            execute_provider(registry, "test.echo", parameters={"factor": 1.0})
        assert "pressure" in excinfo.value.reason
    finally:
        set_governor(None)


# ------------------------------------------------------- built-in reality --
def test_kriging_provider_executes_on_real_engine(tmp_path):
    """The built-in kriging provider must run the production interpolator."""
    from paleo_workbench.mapping.geological_pipeline.models import (
        GeologicalFactor,
        GeologicalFactorDataset,
    )
    from paleo_workbench.providers.builtin.interpolation import KrigingProvider

    dataset = GeologicalFactorDataset(factor_name="thickness", unit="m", crs="EPSG:32650")
    for i in range(12):
        dataset.add_point(
            GeologicalFactor(
                name="thickness",
                value=10.0 + i,
                unit="m",
                well_id=f"w{i}",
                x=100.0 + i * 10.0,
                y=200.0 + i * 7.0,
            )
        )
    provider = KrigingProvider()
    result = execute_provider(provider, inputs={"dataset": dataset}, parameters={"grid_n": 24})
    assert result.artifacts[0].kind == "grid"
    grid = result.artifacts[0].value
    assert grid.grid_z.shape == (24, 24)
    assert result.diagnostics["finite_ratio"] > 0.9
    assert result.diagnostics["algorithm_id"] == "kriging"


def test_kriging_provider_rejects_empty_dataset():
    from paleo_workbench.mapping.geological_pipeline.models import GeologicalFactorDataset
    from paleo_workbench.providers.builtin.interpolation import IDWProvider

    provider = IDWProvider()
    with pytest.raises(ProviderRejectedInputError):
        execute_provider(
            provider,
            inputs={"dataset": GeologicalFactorDataset(factor_name="x")},
            parameters={},
        )


def test_kriging_provider_reproducibility():
    """Deterministic provider: same inputs → identical grid bytes."""
    from paleo_workbench.mapping.geological_pipeline.models import (
        GeologicalFactor,
        GeologicalFactorDataset,
    )
    from paleo_workbench.providers.builtin.interpolation import IDWProvider

    def build():
        dataset = GeologicalFactorDataset(factor_name="sand", unit="%")
        for i in range(9):
            dataset.add_point(
                GeologicalFactor(name="sand", value=float(i), x=10.0 * i, y=5.0 * i)
            )
        return dataset

    provider = IDWProvider()
    r1 = execute_provider(provider, inputs={"dataset": build()}, parameters={"grid_n": 20})
    r2 = execute_provider(provider, inputs={"dataset": build()}, parameters={"grid_n": 20})
    import numpy as np

    assert np.array_equal(r1.artifacts[0].value.grid_z, r2.artifacts[0].value.grid_z)


def test_attribute_provider_rejects_bad_volume():
    from paleo_workbench.providers.builtin.seismic_attribute import SeismicAttributeProvider

    provider = SeismicAttributeProvider("c3", {})
    with pytest.raises(ProviderRejectedInputError):
        execute_provider(provider, inputs={"volume": PathRef(path="/nonexistent.zarr")}, parameters={})


def test_visualization_providers_probe_honesty():
    from paleo_workbench.providers.builtin.map_export import make_visualization_providers

    providers = make_visualization_providers()
    by_id = {p.descriptor.provider_id: p for p in providers}
    assert by_id["viz.map_render.fallback"].available is True
    # QGIS availability is environment-dependent — the flag must simply match
    # the probe, never be hardcoded True.
    assert isinstance(by_id["viz.map_render.qgis"].available, bool)


# ------------------------------------------------ #1137 cancel semantics --
def test_execute_provider_task_cancelled_marks_run_cancelled_and_propagates():
    """TaskCancelled: DataRun terminal state 'cancelled', exception unwrapped."""
    from paleo_workbench.runtime.task_scheduler import TaskCancelled

    class CancelledProvider(EchoProvider):
        def execute(self, inputs, parameters, context):
            raise TaskCancelled("cooperative stop at safe point")

    catalog = FakeCatalog()
    with pytest.raises(TaskCancelled):  # NOT ProviderExecutionError
        execute_provider(
            CancelledProvider(),
            parameters={"factor": 1.0},
            context=ProviderContext(catalog=catalog),
        )
    assert catalog.runs[0]["status"] == "cancelled"


def test_execute_provider_keyboard_interrupt_passes_through_unwrapped():
    class InterruptedProvider(EchoProvider):
        def execute(self, inputs, parameters, context):
            raise KeyboardInterrupt()

    catalog = FakeCatalog()
    with pytest.raises(KeyboardInterrupt):
        execute_provider(
            InterruptedProvider(),
            parameters={"factor": 1.0},
            context=ProviderContext(catalog=catalog),
        )
    # The run is NOT marked "failed" — an interrupt is neither a failure nor
    # a completion; it simply passes through (nothing swallowed).
    assert catalog.runs[0]["status"] == "running"


def test_attribute_provider_propagates_task_cancelled_unwrapped(monkeypatch, tmp_path):
    """#1137: the in-provider job wrapper must not swallow TaskCancelled."""
    import geoviz_seismic
    import paleo_workbench.seismic_attributes as attrs_mod
    from paleo_workbench.providers.builtin.seismic_attribute import SeismicAttributeProvider
    from paleo_workbench.runtime.task_scheduler import TaskCancelled

    class FakeJob:
        def __init__(self, reader, dst, kernel):
            pass

        def run(self, ctx):
            raise TaskCancelled("stop at band 3")

    monkeypatch.setattr(geoviz_seismic, "open_volume", lambda path: object())
    monkeypatch.setattr(attrs_mod, "VolumeAttributeJob", FakeJob)
    provider = SeismicAttributeProvider("c3", {})
    with pytest.raises(TaskCancelled):
        provider.execute(
            inputs={"volume": PathRef(path=str(tmp_path / "v.zarr"))},
            parameters={"output_dir": str(tmp_path / "out" / "attr.zarr")},
            context=ProviderContext(),
        )


# -------------------------------------------------- #1160 finite ratio --
def test_roi_finite_ratio_counts_nan_as_non_finite(monkeypatch, tmp_path):
    import geoviz_seismic
    import numpy as np
    import paleo_workbench.seismic_attributes as attrs_mod
    from paleo_workbench.providers.builtin.seismic_attribute import SeismicAttributeProvider

    monkeypatch.setattr(geoviz_seismic, "open_volume", lambda path: object())
    monkeypatch.setattr(
        attrs_mod, "roi_attribute", lambda reader, bounds, name: np.full((4, 4, 8), np.nan)
    )
    provider = SeismicAttributeProvider("c3", {})
    result = provider.execute(
        inputs={"volume": PathRef(path=str(tmp_path / "v.zarr"))},
        parameters={"roi": {"il0": 0, "il1": 4, "xl0": 0, "xl1": 4, "t0": 0, "t1": 8}},
        context=ProviderContext(),
    )
    assert result.diagnostics["finite_ratio"] == 0.0  # all-NaN ROI: nothing finite


# ---------------------------------------------- #1180 degraded admission --
def test_governor_import_failure_fails_loud_and_marks_degraded(monkeypatch, caplog):
    """A broken first-party admission module never becomes a silent pass."""
    import sys

    from paleo_workbench.providers import execution as provider_execution

    provider_execution.reset_governor_degraded()
    monkeypatch.setitem(sys.modules, "paleo_workbench.runtime.resource_governor", None)
    try:
        with caplog.at_level("ERROR"):
            with pytest.raises(RuntimeError, match="without resource admission"):
                provider_execution.execute_provider(EchoProvider(), parameters={"factor": 1.0})
        assert provider_execution.GOVERNOR_DEGRADED is True
        assert any("falling back" in r.message for r in caplog.records)
    finally:
        provider_execution.reset_governor_degraded()


def test_governor_singleton_broken_degrades_to_default_budget_admission(monkeypatch, caplog):
    """Import failure at admit time → conservative default-budget lease, run continues."""
    from paleo_workbench.runtime import resource_governor as rg
    from paleo_workbench.providers import execution as provider_execution

    def broken_get_governor():
        raise ImportError("governor singleton broken")

    provider_execution.reset_governor_degraded()
    monkeypatch.setattr(rg, "get_governor", broken_get_governor)
    try:
        with caplog.at_level("ERROR"):
            result = provider_execution.execute_provider(
                EchoProvider(), parameters={"factor": 1.0}
            )
        assert result.metrics["worked"] is True  # provider still ran — guarded
        assert provider_execution.GOVERNOR_DEGRADED is True
        assert any("falling back" in r.message for r in caplog.records)
    finally:
        provider_execution.reset_governor_degraded()


def test_degraded_fallback_governor_is_one_shared_instance():
    """P2/#1180: every degraded admission leases from the SAME fallback
    governor — a fresh governor per call would hand each fallback execution
    its own unlimited budget, so concurrent degraded admissions would never
    aggregate against one another."""
    from paleo_workbench.providers import execution as provider_execution

    provider_execution.reset_fallback_governor()
    lease1 = lease2 = None
    try:
        lease1 = provider_execution.default_budget_lease(
            category_value="interactive.query",
            title="fallback-1",
            estimated_cpu_cores=0.5,
        )
        governor_after_first = provider_execution._FALLBACK_GOVERNOR
        assert governor_after_first is not None
        lease2 = provider_execution.default_budget_lease(
            category_value="interactive.query",
            title="fallback-2",
            estimated_cpu_cores=0.5,
        )
        # Same instance across calls (id-identical), not a new governor.
        assert provider_execution._FALLBACK_GOVERNOR is governor_after_first
        assert id(provider_execution._FALLBACK_GOVERNOR) == id(governor_after_first)
    finally:
        for lease in (lease1, lease2):
            if lease is not None:
                lease.release()
        provider_execution.reset_fallback_governor()


# ------------------------------------------- #1177 output containment --
def test_resolve_contained_output_requires_a_root(tmp_path):
    from paleo_workbench.providers.errors import ProviderExecutionError
    from paleo_workbench.providers.paths import resolve_contained_output

    with pytest.raises(ProviderExecutionError, match="cannot be containment-checked"):
        resolve_contained_output(ProviderContext(), "x.png", provider_id="test.echo")


def test_map_export_provider_rejects_out_of_workspace_output(tmp_path):
    """Export destinations must stay inside the context workspace (#1177)."""
    from paleo_workbench.mapping.layers import MapDocument
    from paleo_workbench.providers.errors import ProviderExecutionError

    provider = get_provider_registry().get("export.map_product")
    document = MapDocument(title="t")
    context = ProviderContext(workspace_root=str(tmp_path))
    for escape in ("../escape.png", "/definitely-outside/escape.png"):
        with pytest.raises(ProviderExecutionError, match="outside the execution workspace"):
            execute_provider(
                provider,
                inputs={"document": document},
                parameters={"output_path": escape},
                context=context,
            )


# --------------------------------------- #1176 model trust chain (provider) --
class _FakeModelService:
    def __init__(self, versions):
        self._versions = versions

    def list_model_versions(self, model_id=None):
        return list(self._versions)


def _sha256_of(path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_model_file(tmp_path, content: bytes = b"onnx-model-bytes"):
    path = tmp_path / "model.onnx"
    path.write_bytes(content)
    return path


def test_inference_provider_rejects_unregistered_model(tmp_path, monkeypatch):
    """Unregistered model artifact → fail closed before any inference runs."""
    from types import SimpleNamespace

    import paleo_workbench.prediction.tiled_onnx as prediction_tiled_onnx
    from paleo_workbench.providers.builtin.inference import TiledOnnxCapabilityProvider
    from paleo_workbench.providers.errors import ProviderRejectedInputError

    model_file = _make_model_file(tmp_path)
    # A registry that knows about a DIFFERENT artifact only.
    other = tmp_path / "other.onnx"
    other.write_bytes(b"other")
    service = _FakeModelService(
        [
            SimpleNamespace(
                model_id="m-other",
                model_version="1",
                artifact_uri=str(other),
                checksum=_sha256_of(other),
            )
        ]
    )
    catalog = SimpleNamespace(service=service)

    ran = []

    class RecordingDelegate:
        model_id = "delegate"
        model_version = "1"

        def run(self, inputs, parameters):
            ran.append(True)
            return {"volume_outputs": {}, "generator_version": "x"}

    monkeypatch.setattr(prediction_tiled_onnx, "TiledOnnxProvider", RecordingDelegate)
    provider = TiledOnnxCapabilityProvider()
    with pytest.raises(ProviderRejectedInputError, match="not registered"):
        execute_provider(
            provider,
            inputs={"volume": PathRef(path=str(tmp_path / "v.zarr"))},
            parameters={"model_path": str(model_file), "classes": 4},
            context=ProviderContext(catalog=catalog),
        )
    assert ran == []  # never reached inference


def test_inference_provider_verified_provenance_for_registered_model(tmp_path, monkeypatch):
    """Registered model: real sha256 + registered identity in provenance."""
    from types import SimpleNamespace

    import paleo_workbench.prediction.tiled_onnx as prediction_tiled_onnx
    from paleo_workbench.providers.builtin.inference import TiledOnnxCapabilityProvider

    model_file = _make_model_file(tmp_path)
    digest = _sha256_of(model_file)
    service = _FakeModelService(
        [
            SimpleNamespace(
                model_id="facies-v2",
                model_version="3",
                artifact_uri="",  # registered by checksum only
                checksum=digest,
            )
        ]
    )
    catalog = SimpleNamespace(service=service)

    class Delegate:
        model_id = "tiled-onnx-seismic"
        model_version = "tiled-onnx-v1"

        def run(self, inputs, parameters):
            return {
                "volume_outputs": {"classmap": {"store": str(tmp_path / "cm.zarr")}},
                "generator_version": self.model_version,
                "warnings": [],
            }

    monkeypatch.setattr(prediction_tiled_onnx, "TiledOnnxProvider", Delegate)
    provider = TiledOnnxCapabilityProvider()
    result = execute_provider(
        provider,
        inputs={"volume": PathRef(path=str(tmp_path / "v.zarr"))},
        parameters={"model_path": str(model_file), "classes": 4},
        context=ProviderContext(catalog=catalog),
    )
    prov = result.provenance
    assert prov["registered"] is True
    assert prov["model_id"] == "facies-v2"  # registry identity, not delegate label
    assert prov["model_version"] == "3"
    assert prov["model_checksum_sha256"] == digest  # REAL checksum of the file
    assert prov["registered_match"] == "checksum"


def test_inference_provider_rejects_checksum_mismatch(tmp_path, monkeypatch):
    """artifact_uri match but tampered file → refuse (trusted inference)."""
    from types import SimpleNamespace

    import paleo_workbench.prediction.tiled_onnx as prediction_tiled_onnx
    from paleo_workbench.providers.builtin.inference import TiledOnnxCapabilityProvider
    from paleo_workbench.providers.errors import ProviderRejectedInputError

    model_file = _make_model_file(tmp_path, content=b"tampered-content")
    service = _FakeModelService(
        [
            SimpleNamespace(
                model_id="m",
                model_version="1",
                artifact_uri=str(model_file),
                checksum="0" * 64,  # registration pins a different digest
            )
        ]
    )
    catalog = SimpleNamespace(service=service)

    class Delegate:
        def run(self, inputs, parameters):
            return {}

    monkeypatch.setattr(prediction_tiled_onnx, "TiledOnnxProvider", Delegate)
    provider = TiledOnnxCapabilityProvider()
    with pytest.raises(ProviderRejectedInputError, match="checksum mismatch"):
        execute_provider(
            provider,
            inputs={"volume": PathRef(path=str(tmp_path / "v.zarr"))},
            parameters={"model_path": str(model_file), "classes": 4},
            context=ProviderContext(catalog=catalog),
        )


def test_inference_provider_rejects_unreachable_registry(tmp_path, monkeypatch):
    """No model registry reachable → fail closed (cannot prove registration)."""
    import paleo_workbench.catalog.runtime as catalog_runtime
    from paleo_workbench.providers.builtin.inference import TiledOnnxCapabilityProvider
    from paleo_workbench.providers.errors import ProviderRejectedInputError

    model_file = _make_model_file(tmp_path)
    monkeypatch.setattr(catalog_runtime, "get_catalog_service", lambda: None)
    provider = TiledOnnxCapabilityProvider()
    with pytest.raises(ProviderRejectedInputError, match="no reachable model registry"):
        execute_provider(
            provider,
            inputs={"volume": PathRef(path=str(tmp_path / "v.zarr"))},
            parameters={"model_path": str(model_file), "classes": 4},
            context=ProviderContext(),  # no catalog at all
        )
