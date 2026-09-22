"""Process runtime: heavy-task scheduling, budgets and resource governance.

Public surface (P2-A adds the governor family on top of the #1081 scheduler
and budget — there is still exactly one scheduler, one budget, one governor):
"""

from paleo_workbench.runtime.cancellation import (
    CancellationSource,
    CancellationToken,
    as_event,
    cancel_callable,
)
from paleo_workbench.runtime.governance import ensure_global_governance
from paleo_workbench.runtime.memory_pressure import (
    MemoryPressureMonitor,
    PressureState,
    get_pressure_monitor,
    set_pressure_monitor,
)
from paleo_workbench.runtime.resource_budget import (
    ResourceBudget,
    active_budget,
    apply_all_budgets,
    apply_compute_budget,
    apply_l1_budget,
    apply_vram_budget,
    set_budget,
)
from paleo_workbench.runtime.resource_governor import (
    ResourceExhausted,
    ResourceGovernor,
    ResourceLease,
    TaskRequest,
    configure_runtime_budget,
    get_governor,
    set_governor,
)
from paleo_workbench.runtime.task_categories import (
    CATEGORY_POLICIES,
    CategoryPolicy,
    TaskCategory,
    category_for_kind,
    policy_for,
)
from paleo_workbench.runtime.task_scheduler import (
    TaskCancelled,
    TaskContext,
    TaskHandle,
    TaskScheduler,
    TaskSpec,
    TaskState,
    get_scheduler,
    reset_global_scheduler,
)
from paleo_workbench.runtime.telemetry import snapshot as runtime_snapshot

__all__ = [
    "CATEGORY_POLICIES",
    "CancellationSource",
    "CancellationToken",
    "CategoryPolicy",
    "MemoryPressureMonitor",
    "PressureState",
    "ResourceBudget",
    "ResourceExhausted",
    "ResourceGovernor",
    "ResourceLease",
    "TaskCancelled",
    "TaskCategory",
    "TaskContext",
    "TaskHandle",
    "TaskRequest",
    "TaskScheduler",
    "TaskSpec",
    "TaskState",
    "active_budget",
    "apply_all_budgets",
    "apply_compute_budget",
    "apply_l1_budget",
    "apply_vram_budget",
    "as_event",
    "cancel_callable",
    "category_for_kind",
    "configure_runtime_budget",
    "ensure_global_governance",
    "get_governor",
    "get_pressure_monitor",
    "get_scheduler",
    "policy_for",
    "reset_global_scheduler",
    "runtime_snapshot",
    "set_budget",
    "set_governor",
    "set_pressure_monitor",
]
