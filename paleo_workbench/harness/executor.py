"""Guarded harness executor (P2-C).

The execution loop every agent request goes through:

    ActionRequest (action_id + parameters)
      → spec lookup (unknown = explicit error)
      → parameter schema validation
      → permission check (risk vs context permissions)
      → required-context resolution
      → resource admission (governor lease from the spec profile)
      → execute (handler over domain services, or capability provider)
      → verify (scientific / map validation hooks)
      → ActionResult (status, outputs, verification, warnings, metrics)

The harness never pretends to be an LLM: planning happens outside; this
pipeline only exposes, validate, execute and verify. Handlers do real work
through the domain services; the executor owns the guard rails.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.registry import ActionRegistry
from paleo_workbench.harness.spec import ActionRisk, ActionSpec
from paleo_workbench.harness.validation import (
    FAIL,
    PASS,
    WARNING,
    MapValidationHook,
    ScientificValidator,
)
from paleo_workbench.providers.errors import InvalidParametersError
from paleo_workbench.providers.execution import default_budget_lease, validate_parameters
from paleo_workbench.runtime.task_scheduler import TaskCancelled

logger = logging.getLogger(__name__)

#: #1180: set when the first-party runtime admission modules failed to
#: import. Actions then admit through the conservative default-budget
#: fallback — never an unguarded pass. Mirrors
#: :data:`paleo_workbench.providers.execution.GOVERNOR_DEGRADED`.
ADMISSION_DEGRADED = False


def reset_admission_degraded() -> None:
    """Test helper: clear the #1180 degraded marker."""
    global ADMISSION_DEGRADED
    ADMISSION_DEGRADED = False


class ActionPermissionError(PermissionError):
    def __init__(self, action_id: str, risk: ActionRisk):
        self.action_id = action_id
        self.risk = risk
        super().__init__(f"action {action_id!r} requires {risk.value} permission")


class ActionContextError(LookupError):
    pass


class ActionValidationError(ValueError):
    def __init__(self, action_id: str, problems: list[str]):
        self.problems = problems
        super().__init__(f"parameters for {action_id!r} invalid: {'; '.join(problems)}")


@dataclass(slots=True)
class ActionResult:
    action_id: str
    status: str = "ok"  # ok | warning | fail | cancelled
    outputs: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status,
            "outputs": _jsonable(self.outputs),
            "verification": _jsonable(self.verification),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


# Hooks the executor consults after handler execution; handlers flag outputs
# for verification by returning them in known shapes (see _verify).
ScientificValidatorFn = Callable[[Any], Any]
MapValidatorFn = Callable[[Any, Any], Any]


class HarnessExecutor:
    def __init__(
        self,
        registry: ActionRegistry | None = None,
        *,
        scientific_validator: ScientificValidator | None = None,
        map_validator: MapValidationHook | None = None,
    ) -> None:
        from paleo_workbench.harness.registry import get_action_registry

        self._registry = registry if registry is not None else get_action_registry()
        self._scientific = scientific_validator or ScientificValidator()
        self._map = map_validator or MapValidationHook()

    # ------------------------------------------------------------ execute --
    def execute(self, action_id: str, parameters: dict[str, Any] | None = None,
                context: ActionContext | None = None) -> ActionResult:
        parameters = dict(parameters or {})
        context = context or ActionContext()
        t0 = time.perf_counter()
        result = ActionResult(action_id=action_id)

        try:
            spec = self._registry.get(action_id)
        except LookupError as exc:
            result.status = "fail"
            result.error = str(exc)
            result.elapsed_ms = (time.perf_counter() - t0) * 1000
            return result

        try:
            problems = validate_parameters(
                spec.input_schema or {"type": "object"}, parameters
            )
            if problems:
                raise ActionValidationError(action_id, problems)
            if not context.permits(spec.risk):
                raise ActionPermissionError(action_id, spec.risk)
            for attr in spec.required_context:
                if not context.has(attr):
                    raise ActionContextError(
                        f"action {action_id!r} requires context.{attr} "
                        f"({', '.join(spec.required_context)} must be set)"
                    )
        except (ActionValidationError, ActionPermissionError, ActionContextError) as exc:
            result.status = "fail"
            result.error = str(exc)
            result.elapsed_ms = (time.perf_counter() - t0) * 1000
            return result

        lease = None
        try:
            lease = self._admit(spec)
            payload = self._execute_spec(spec, parameters, context, result)
            self._validate_output(spec, payload)
            verification = self._verify(spec, payload, parameters, context)
            result.verification = verification
            if isinstance(payload, dict):
                result.outputs = payload
            else:
                result.outputs = {"value": payload}
            if verification.get("verdict") == FAIL:
                result.status = "fail"
                result.error = "verification failed: " + "; ".join(
                    r for r in verification.get("reasons", []) if r
                )
            elif verification.get("verdict") == WARNING:
                result.status = "warning"
                result.warnings.extend(verification.get("reasons", []))
        except (ActionValidationError, InvalidParametersError) as exc:
            result.status = "fail"
            result.error = str(exc)
        except TaskCancelled as exc:
            # #1137: cooperative cancellation is a first-class terminal
            # outcome — "cancelled", never "fail". Returning (instead of
            # re-raising) keeps the executor's isolation contract: the loop
            # never crashes, and scheduler-side callers detect the cancel
            # through their cancellation token and land in CANCELLED.
            result.status = "cancelled"
            result.error = f"cancelled: {exc}"
        except PermissionError as exc:
            result.status = "fail"
            result.error = str(exc)
        except LookupError as exc:
            result.status = "fail"
            result.error = str(exc)
        except Exception as exc:  # isolation: handler errors never crash the loop
            logger.exception("harness action %s failed", action_id)
            result.status = "fail"
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            if lease is not None:
                lease.release()
            result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return result

    # dispatch convenience ------------------------------------------------
    def __call__(self, action_id: str, **parameters: Any) -> ActionResult:
        return self.execute(action_id, parameters)

    # ------------------------------------------------------------ helpers --
    def _execute_spec(self, spec: ActionSpec, parameters: dict[str, Any],
                      context: ActionContext, result: ActionResult) -> Any:
        if spec.provider_id is not None:
            from paleo_workbench.providers import ProviderContext, execute_provider
            from paleo_workbench.providers.refs import PathRef, SeismicVolumeRef

            # Provider-declared actions resolve their typed inputs from the
            # context (never smuggled through the schema-validated params).
            inputs = {}
            volume = context.active_volume
            if isinstance(volume, (SeismicVolumeRef, PathRef)):
                inputs["volume"] = volume
            from pathlib import Path

            workspace_root = (
                str(Path(context.project_path).parent)
                if context.project_path
                else str(Path.cwd())
            )
            provider_context = ProviderContext(
                catalog=context.catalog,
                workspace_root=workspace_root,
                emit_progress=context.progress,
                cancel=context.cancel,
                work_dir=context.extras.get("work_dir"),
            )
            provider_result = execute_provider(
                self._provider_registry(), spec.provider_id,
                inputs=inputs, parameters=parameters, context=provider_context,
            )
            result.warnings.extend(provider_result.warnings)
            result.metrics.update(provider_result.metrics)
            result.metrics["provenance"] = provider_result.provenance
            # Hand artifacts back for verification + caller access.
            values = [a.value for a in provider_result.artifacts if a.value is not None]
            payload: dict[str, Any] = {"provider": spec.provider_id, "artifacts": provider_result.to_dict()["artifacts"]}
            if values:
                payload["values"] = values
            return payload
        handler = spec.handler
        if handler is None:
            raise RuntimeError(f"action {spec.action_id} has neither handler nor provider")
        return handler(context, parameters)

    @staticmethod
    def _provider_registry():
        from paleo_workbench.providers import get_provider_registry

        return get_provider_registry()

    @staticmethod
    def _validate_output(spec: ActionSpec, payload: Any) -> None:
        """Enforce a declared ``output_schema`` on the action payload (#1178).

        Minimal-but-real: the top-level required keys and types of the
        payload dict must match the schema. A violation raises
        :class:`ActionValidationError` (caught by the loop → status "fail"
        with the reasons) — a shape-mismatched result is never silently
        passed to the caller. Schemas that declare nothing stay unchecked.
        """
        schema = spec.output_schema
        if not schema or not isinstance(payload, dict):
            return
        problems = validate_parameters(schema, payload, label="output")
        if problems:
            raise ActionValidationError(spec.action_id, problems)

    def _admit(self, spec: ActionSpec):
        global ADMISSION_DEGRADED
        try:
            from paleo_workbench.runtime.resource_governor import TaskRequest, get_governor
            from paleo_workbench.runtime.task_categories import TaskCategory

            profile = spec.resource_profile
            category = TaskCategory(spec.category)
            return get_governor().admit(
                TaskRequest(
                    category=category,
                    title=f"action:{spec.action_id}",
                    estimated_cpu_cores=float(profile.get("estimated_cpu_cores", 0.5)),
                    estimated_ram_bytes=int(profile.get("estimated_ram_bytes", 0)),
                    estimated_vram_bytes=int(profile.get("estimated_vram_bytes", 0)),
                    io_weight=profile.get("io_weight", 0.5),
                )
            )
        except ImportError as exc:
            # #1180: an ImportError of first-party runtime modules is never a
            # silent "no admission" pass — same contract as the provider
            # executor: log, mark degraded, retry against a conservative
            # default-budget governor, or fail loudly.
            ADMISSION_DEGRADED = True
            logger.error(
                "first-party resource admission modules unavailable for action %s "
                "(%s); falling back to conservative default-budget admission",
                spec.action_id,
                exc,
            )
            profile = spec.resource_profile
            try:
                return default_budget_lease(
                    category_value=spec.category,
                    title=f"action:{spec.action_id} (degraded-admission)",
                    estimated_cpu_cores=float(profile.get("estimated_cpu_cores", 0.5)),
                    estimated_ram_bytes=int(profile.get("estimated_ram_bytes", 0)),
                    estimated_vram_bytes=int(profile.get("estimated_vram_bytes", 0)),
                    io_weight=profile.get("io_weight", 0.5),
                )
            except ImportError as fallback_exc:
                raise RuntimeError(
                    f"first-party runtime admission modules are broken ({exc}); refusing "
                    f"to execute action {spec.action_id!r} without resource admission"
                ) from fallback_exc
        # ResourceExhausted propagates deliberately — pressure shedding is a
        # first-class outcome the agent must see, not a silent queue.

    def _verify(self, spec: ActionSpec, payload: Any, parameters: dict[str, Any],
                context: ActionContext) -> dict[str, Any]:
        verification: dict[str, Any] = {}
        values: list[Any] = []
        if isinstance(payload, dict):
            values = list(payload.get("values", []))
        elif payload is not None:
            values = [payload]
        grid_reports = []
        for value in values:
            if hasattr(value, "grid_z") or (hasattr(value, "ndim") and getattr(value, "ndim", 0) >= 1):
                grid_reports.append(self._scientific.validate_grid(value, label=spec.action_id).to_dict())
        if grid_reports:
            worst = FAIL if any(r["verdict"] == FAIL for r in grid_reports) else (
                WARNING if any(r["verdict"] == WARNING for r in grid_reports) else PASS
            )
            verification = {"verdict": worst, "reasons": [r for rep in grid_reports for r in rep["reasons"]],
                            "grids": grid_reports}
        # Map validation: handlers may return/flag a map document explicitly.
        document = None
        if isinstance(payload, dict):
            document = payload.get("map_document") or payload.get("document")
        elif hasattr(payload, "to_snapshot") and hasattr(payload, "layers"):
            document = payload
        if document is not None and hasattr(document, "layers"):
            composition = (
                payload.get("composition")
                if isinstance(payload, dict)
                else context.compositions.get(context.current_map_id or "")
            )
            require = bool(parameters.get("require_components"))
            report = self._map.validate(document, composition, require_components=require)
            verification = self._merge(verification, "map", report.to_dict())
        return verification

    @staticmethod
    def _merge(verification: dict[str, Any], key: str, report: dict[str, Any]) -> dict[str, Any]:
        if not verification:
            return {**report, key: report}
        verdicts = [verification.get("verdict"), report.get("verdict")]
        worst = FAIL if FAIL in verdicts else (WARNING if WARNING in verdicts else PASS)
        return {
            "verdict": worst,
            "reasons": list(verification.get("reasons", [])) + list(report.get("reasons", [])),
            key: report,
            **{k: v for k, v in verification.items() if k not in ("verdict", "reasons")},
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict"):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "shape"):  # ndarray summary
        try:
            import numpy as np

            finite = np.isfinite(value)
            return {
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "finite_ratio": float(finite.sum()) / max(1, value.size),
            }
        except Exception:
            pass
    return str(value)
