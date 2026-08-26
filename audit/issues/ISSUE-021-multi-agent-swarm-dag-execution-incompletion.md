# ISSUE-021: Multi-Agent Swarm DAG Execution Incompletion on Upstream Task Failure

- **Severity**: Medium
- **Subproject**: `paleo_workbench` (`paleo_workbench/agent`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/agent/harness.py#L96-L126`
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/agent/planner.py#L43-L63`

---

## Defect Description & Root Cause Analysis

In `paleo_workbench/agent/harness.py`, `PaleoAIHarness.execute_query()` drives an 8-agent swarm DAG workflow:

```python
while not plan.is_finished() and iteration < max_iterations:
    iteration += 1
    ready_nodes = plan.get_executable_nodes()
    if not ready_nodes:
        break
    for node in ready_nodes:
        try:
            # ... execute agent
            node.status = TaskStatus.COMPLETED
        except Exception as exc:
            node.status = TaskStatus.FAILED
            node.error = str(exc)
```

When an upstream task (such as `task_data_discover`) encounters an error and transitions to `TaskStatus.FAILED`, all downstream tasks depending on it (`task_well_process`, `task_gis_spatial`, `task_carto_generate`, `task_viz_compose`) can never become executable because `get_executable_nodes()` requires `node.status == TaskStatus.COMPLETED` for all prerequisites.

Consequently, on the next iteration, `get_executable_nodes()` returns an empty list `[]`, and the `while` loop breaks. However, all downstream nodes are left stranded in `TaskStatus.PENDING`.

When caller code evaluates `plan.is_finished()`:
```python
all(
    node.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}
    for node in self.nodes.values()
)
```
Because the stranded downstream nodes remain in `TaskStatus.PENDING`, `plan.is_finished()` returns `False`. The DAG execution state is left indefinitely incomplete and inconsistent.

---

## Impact Analysis

- **Swarm Orchestration Inconsistency**: The workflow graph reports that execution is not finished (`is_finished() == False`) even though the execution loop has completely terminated.
- **UI Hang / Lockup**: User interface widgets monitoring `plan.is_finished()` or awaiting task completion spinners remain stuck in pending states.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
from paleo_workbench.agent.harness import PaleoAIHarness
from paleo_workbench.agent.planner import TaskStatus

h = PaleoAIHarness()

class FailingAgent:
    def run(self, node, ctx):
        raise RuntimeError("Data source inaccessible")

h.agents["data_agent"] = FailingAgent()
res = h.execute_query("绘制古地理相图")

print("task_data_discover status:", res.plan.nodes["task_data_discover"].status) # FAILED
print("task_carto_generate status:", res.plan.nodes["task_carto_generate"].status) # PENDING
print("plan.is_finished():", res.plan.is_finished()) # Buggy Output: False
```

---

## Concrete Suggested Fix

Cascade failure states to unexecutable downstream dependent tasks by marking them as `TaskStatus.SKIPPED`:

### Patch (`paleo_workbench/agent/harness.py`)
```python
# In PaleoAIHarness.execute_query():
while not plan.is_finished() and iteration < max_iterations:
    iteration += 1
    ready_nodes = plan.get_executable_nodes()
    if not ready_nodes:
        # Cascade skipped status to all remaining unexecutable pending nodes
        for node in plan.nodes.values():
            if node.status == TaskStatus.PENDING:
                node.status = TaskStatus.SKIPPED
                node.error = "Skipped due to upstream task failure or dependency deadlock"
        break
    # ...
```
