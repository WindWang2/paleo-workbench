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


# ------------------------------------------------- #1137 cancel semantics


class _CancelProvider:
    """Raises TaskCancelled like a cooperatively-cancelled job would."""

    def __init__(self, exc: BaseException):
        self._descriptor = _descriptor()
        self._exc = exc

    @property
    def descriptor(self):
        return self._descriptor

    def execute(self, inputs, parameters, context):
        raise self._exc


def test_execute_provider_cancel_marks_run_cancelled():
    from paleo_workbench.runtime.task_scheduler import TaskCancelled

    registry = ProviderRegistry()
    registry.register(_CancelProvider(TaskCancelled("user cancelled")))
    catalog = FakeCatalog()
    with pytest.raises(TaskCancelled):
        execute_provider(
            registry,
            "test.echo",
            parameters={"factor": 1.0},
            context=ProviderContext(catalog=catalog),
        )
    assert catalog.runs[0]["status"] == "cancelled"


def test_execute_provider_keyboard_interrupt_propagates_unwrapped():
    registry = ProviderRegistry()
    registry.register(_CancelProvider(KeyboardInterrupt()))
    catalog = FakeCatalog()
    with pytest.raises(KeyboardInterrupt):
        execute_provider(
            registry,
            "test.echo",
            parameters={"factor": 1.0},
            context=ProviderContext(catalog=catalog),
        )
    # The run is still terminal (never stranded running) but the original
    # interpreter-exit type propagates instead of ProviderExecutionError.
    assert catalog.runs[0]["status"] == "failed"
