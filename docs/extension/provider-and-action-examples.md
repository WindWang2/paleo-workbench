# Extension Examples — Provider SDK & Agent Harness (P2)

Two minimal, real examples. They document the *shape*; the built-ins in
`paleo_workbench/providers/builtin/` and actions in
`paleo_workbench/harness/actions/` are the production references.

## 1. Minimal capability provider

```python
from paleo_workbench.providers import (
    ProviderDescriptor, ProviderFamily, ResourceProfile, ProviderResult,
    ArtifactRef,
)
from paleo_workbench.providers.refs import FactorDatasetRef


class WeightedKriging:
    """Registers alongside the built-ins; wraps your own interpolation."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="interpolation.weighted_kriging",   # unique, dotted
            family=ProviderFamily.INTERPOLATION,
            version="1.0.0",                                 # numeric dotted
            display_name="加权克里金",
            description="My weighted kriging over well factor points.",
            input_types=("FactorDatasetRef", "GeologicalFactorDataset"),
            output_types=("FactorGridRef",),
            parameters_schema={
                "type": "object",
                "properties": {
                    "grid_n": {"type": "integer", "minimum": 8, "maximum": 1000},
                    "weight": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["grid_n"],
                "additionalProperties": False,
            },
            resource_profile=ResourceProfile(
                estimated_cpu_cores=2.0,          # governor admission uses this
                estimated_ram_bytes=256 * 1024**2,
                io_weight=0.5,
                category="background.compute",    # TaskCategory value
            ),
            supports_cancel=True,
            deterministic=True,
        )

    def execute(self, inputs, parameters, context):
        dataset = inputs["dataset"]               # typed ref or domain object
        context.report_progress(0.1, "插值中")
        grid = my_engine.run(dataset, **parameters)   # your real computation
        context.check_cancelled()                 # cooperative cancel point
        context.report_progress(1.0, "完成")
        # Data outputs MUST enter the catalog when one is bound:
        version = None
        if context.catalog and context.run_id:
            version = context.catalog.register_derived(
                run_id=context.run_id, name="weighted-kriging",
                path=str(grid.artifact_path), kind="grid",
            )
        return ProviderResult(
            artifacts=[ArtifactRef(name="grid", kind="grid", value=grid,
                                   version=version)],
        )


# Registration (explicit — no directory scanning):
from paleo_workbench.providers import get_provider_registry
get_provider_registry().register(WeightedKriging())

# Optional distribution-level discovery (opt-in at launch):
#   [project.entry-points."paleo_workbench.providers"]
#   weighted_kriging = "my_pkg.providers:WeightedKriging"
# then: PALEO_PROVIDER_ENTRY_POINTS=1 paleo-workbench
```

What you get for free: structural validation on register, duplicate/version
conflict detection + quarantine isolation, JSON-schema parameter checks,
typed-input enforcement, governor admission (pressure shedding included), a
DataRun provenance wrapper, and agent visibility.

## 2. Minimal harness action

```python
from paleo_workbench.harness import ActionSpec
from paleo_workbench.harness.spec import ActionRisk
from paleo_workbench.harness.registry import get_action_registry


def grid_statistics(context, parameters):
    """COMPUTE action over the active volume via a provider."""
    volume = context.require("active_volume")    # required_context enforced
    from paleo_workbench.providers import execute_provider, ProviderContext
    result = execute_provider(
        None, provider_id="seismic.attribute.c3",
        inputs={"volume": volume}, parameters={},
        context=ProviderContext(catalog=context.catalog, cancel=context.cancel),
    )
    return {"artifacts": result.to_dict()["artifacts"],
            "values": [a.value for a in result.artifacts if a.value is not None]}


get_action_registry().register(ActionSpec(
    action_id="seismic.grid_statistics",          # <domain>.<name>
    description="Compute coherence statistics on the active volume.",
    handler=grid_statistics,
    risk=ActionRisk.COMPUTE,                      # READ | COMPUTE | WRITE
    required_context=("active_volume",),
    input_schema={"type": "object", "properties": {},
                  "additionalProperties": False},
    resource_profile={"estimated_cpu_cores": 2.0, "io_weight": 1.0},
    supports_cancel=True,
))

# Execute (agent or test):
from paleo_workbench.harness import ActionContext, HarnessExecutor
result = HarnessExecutor().execute(
    "seismic.grid_statistics", {}, ActionContext(active_volume=my_ref)
)
assert result.ok
```

Agent tool schemas are *derived* — never hand-written:

```python
from paleo_workbench.harness.registry import get_action_registry
schemas = get_action_registry().tool_schemas()   # OpenAI/Gemini function shape
```

## Boundaries to keep

- Providers/actions receive **typed refs**, never anonymous dicts or agent
  raw paths; data outputs go through the catalog.
- No shell/eval/arbitrary-SQL anywhere; DESTRUCTIVE actions are refused at
  registration; export paths stay inside the workspace and never overwrite.
- See ADR 0064/0065/0066 for the governance/SDK/harness decisions.
