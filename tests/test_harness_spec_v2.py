"""Harness 2.0 contract tests: ActionSpec V2 fields, six canonical result
statuses, verifier hook, cacheability gates, recursive schema-shape checks."""
from __future__ import annotations

import pytest

from paleo_workbench.harness import (
    ActionRegistry,
    ActionResult,
    ActionRisk,
    ActionSpec,
    ActionStatus,
    HarnessExecutor,
    validate_action_spec,
)
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.executor import ActionUnavailableError


def _spec(**overrides) -> ActionSpec:
    fields = {
        "action_id": "demo.v2",
        "description": "V2 contract demo action",
        "handler": lambda ctx, p: {"value": 42},
        "risk": ActionRisk.READ,
    }
    fields.update(overrides)
    return ActionSpec(**fields)


class TestSpecV2Fields:
    def test_version_and_flags_default_backwards_compatible(self):
        spec = _spec()
        assert spec.version == "1.0"
        assert spec.deterministic is False
        assert spec.cacheable is False
        assert spec.idempotent is False
        assert spec.domain_tags == ()
        d = spec.to_dict()
        assert d["version"] == "1.0" and d["cacheable"] is False

    def test_version_must_be_numeric_dotted(self):
        problems = validate_action_spec(_spec(version="v2-beta"))
        assert any("numeric dotted" in p for p in problems)

    def test_cacheable_requires_deterministic(self):
        problems = validate_action_spec(_spec(cacheable=True))
        assert any("cacheable requires deterministic" in p for p in problems)

    def test_cacheable_requires_output_refs(self):
        problems = validate_action_spec(_spec(cacheable=True, deterministic=True))
        assert any("output_refs" in p for p in problems)

    def test_cacheable_deterministic_with_catalog_refs_is_valid(self):
        spec = _spec(
            cacheable=True,
            deterministic=True,
            output_refs=("DataVersionRef",),
            input_refs=("FactorDatasetRef",),
        )
        assert validate_action_spec(spec) == []

    def test_unknown_typed_ref_rejected(self):
        problems = validate_action_spec(_spec(input_refs=("MysteryRef",)))
        assert any("MysteryRef" in p for p in problems)

    def test_verifier_must_be_callable(self):
        problems = validate_action_spec(_spec(verifier="not-callable"))
        assert any("callable" in p for p in problems)

    def test_domain_tags_must_be_lowercase_tokens(self):
        problems = validate_action_spec(_spec(domain_tags=("Geology",)))
        assert any("domain_tag" in p for p in problems)


class TestRecursiveSchemaShape:
    def test_unknown_nested_type_name_reported_at_registration(self):
        schema = {
            "type": "object",
            "properties": {
                "roi": {
                    "type": "object",
                    "properties": {"il0": {"type": "intiger"}},
                }
            },
        }
        problems = validate_action_spec(_spec(input_schema=schema))
        assert any("unknown type 'intiger'" in p for p in problems)

    def test_non_dict_properties_reported(self):
        problems = validate_action_spec(
            _spec(input_schema={"type": "object", "properties": ["a"]})
        )
        assert any("properties" in p for p in problems)

    def test_bad_items_reported(self):
        problems = validate_action_spec(
            _spec(input_schema={"type": "object", "properties": {"xs": {"type": "array", "items": [1]}}})
        )
        assert any("items" in p for p in problems)

    def test_valid_nested_schema_passes(self):
        schema = {
            "type": "object",
            "properties": {
                "roi": {
                    "type": "object",
                    "required": ["il0"],
                    "properties": {"il0": {"type": "integer", "minimum": 0}},
                },
                "names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
        }
        assert validate_action_spec(_spec(input_schema=schema)) == []


class TestSixStatuses:
    @pytest.mark.parametrize(
        "value", ["success", "degraded", "failed", "cancelled", "rejected", "unavailable"]
    )
    def test_vocabulary(self, value):
        assert ActionStatus(value).value == value

    def test_unknown_action_is_rejected(self):
        registry = ActionRegistry()
        result = HarnessExecutor(registry).execute("no.such", {})
        assert result.status == ActionStatus.REJECTED.value
        assert "unknown harness action" in (result.error or "")

    def test_permission_refusal_is_rejected(self):
        registry = ActionRegistry()
        registry.register(_spec())
        result = HarnessExecutor(registry).execute("demo.v2", {}, ActionContext(permissions=frozenset()))
        assert result.status == ActionStatus.REJECTED.value

    def test_handler_exception_is_failed(self):
        def boom(ctx, p):
            raise RuntimeError("boom")

        registry = ActionRegistry()
        registry.register(_spec(handler=boom))
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.FAILED.value
        assert "boom" in result.error

    def test_capability_gap_is_unavailable(self):
        def no_engine(ctx, p):
            raise ActionUnavailableError("correlation engine not configured")

        registry = ActionRegistry()
        registry.register(_spec(handler=no_engine))
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.UNAVAILABLE.value
        assert result.ok is False

    def test_missing_module_is_unavailable(self):
        def needs_backend(ctx, p):
            import no_such_module_anywhere  # noqa: F401

        registry = ActionRegistry()
        registry.register(_spec(handler=needs_backend))
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.UNAVAILABLE.value

    def test_degraded_is_positive_with_warnings(self):
        from paleo_workbench.harness.validation import WARNING, ValidationReport

        def verifier(payload, parameters, context):
            return ValidationReport(verdict=WARNING, reasons=["thin coverage"])

        registry = ActionRegistry()
        registry.register(_spec(verifier=verifier))
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.DEGRADED.value
        assert result.ok is True
        assert result.degraded is True
        assert any("thin coverage" in w for w in result.warnings)

    def test_success_has_canonical_status(self):
        registry = ActionRegistry()
        registry.register(_spec())
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.SUCCESS.value
        assert result.ok is True


class TestVerifierHook:
    def test_verifier_fail_fails_the_action(self):
        def verifier(payload, parameters, context):
            return {"verdict": "fail", "reasons": ["grid not plausible"]}

        registry = ActionRegistry()
        registry.register(_spec(verifier=verifier))
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.FAILED.value
        assert "grid not plausible" in result.error
        assert result.verification["verifier"]["verdict"] == "fail"

    def test_verifier_crash_fails_closed(self):
        def verifier(payload, parameters, context):
            raise ValueError("verifier bug")

        registry = ActionRegistry()
        registry.register(_spec(verifier=verifier))
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.FAILED.value
        assert "verifier crashed" in result.error

    def test_verifier_receives_payload_and_parameters(self):
        seen = {}

        def verifier(payload, parameters, context):
            seen["payload"] = payload
            seen["parameters"] = parameters
            return {"verdict": "pass", "reasons": []}

        registry = ActionRegistry()
        registry.register(_spec(verifier=verifier))
        HarnessExecutor(registry).execute("demo.v2", {"x": 1})
        assert seen["payload"]["value"] == 42
        assert seen["parameters"] == {"x": 1}

    def test_validation_report_object_accepted(self):
        from paleo_workbench.harness.validation import PASS, ValidationReport

        registry = ActionRegistry()
        registry.register(
            _spec(verifier=lambda p, a, c: ValidationReport(verdict=PASS, reasons=[]))
        )
        result = HarnessExecutor(registry).execute("demo.v2", {})
        assert result.status == ActionStatus.SUCCESS.value


class TestResourceExhausted:
    def test_governor_refusal_is_rejected_not_failed(self):
        from paleo_workbench.runtime import ResourceBudget, ResourceGovernor, set_governor
        from paleo_workbench.runtime.memory_pressure import MemoryPressureMonitor, PressureState
        from paleo_workbench.runtime.resource_governor import ResourceExhausted

        monitor = MemoryPressureMonitor(ResourceBudget(), sampler=lambda b: (0.1, 0, 0))
        monitor._state = PressureState.NORMAL  # noqa: SLF001
        # A 2-core machine: a background request beyond the 1-core ceiling
        # is refused by the CPU column.
        gov = ResourceGovernor(ResourceBudget(logical_cores=2), pressure_monitor=monitor)
        set_governor(gov)
        try:
            registry = ActionRegistry()
            ceiling = float(gov.runtime_status()["budget"]["background_cores_effective"])
            registry.register(
                _spec(
                    handler=lambda ctx, p: {"never": True},
                    category="background.compute",
                    resource_profile={
                        "estimated_cpu_cores": ceiling + 50.0,
                        "estimated_ram_bytes": 0,
                        "io_weight": 0.0,
                    },
                )
            )
            result = HarnessExecutor(registry).execute("demo.v2", {})
            assert result.status == ActionStatus.REJECTED.value
            assert "cpu" in (result.error or "")
        finally:
            set_governor(None)
        # Reference kept for readability of the refusal contract.
        assert ResourceExhausted is not None
