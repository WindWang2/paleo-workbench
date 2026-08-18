"""WorkflowOrchestrator: headless workflow step-transition helper.

Legacy helper kept for tests/scripting: authoritative step state inference
and persistence live in :func:`paleo_workbench.workflow.service.home_workflow_steps`
(single source of truth). This orchestrator only advances a cursor; it never
persists state, so production UI must not rely on it (audit #847-2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from paleo_workbench.project.models import ProjectDocument, ProjectMeta
from paleo_workbench.workflow.service import infer_workflow_step_status, STEP_ORDER


@dataclass
class WorkflowStepContext:
    """Read-only context for the active workflow step."""

    step_id: str
    step_name: str
    index: int
    total_steps: int
    is_valid: bool
    prerequisites: list[str]
    status: str


@dataclass
class StepTransitionResult:
    """Result payload returned by orchestrator.next_step()."""

    success: bool
    message: str
    step_context: WorkflowStepContext


class WorkflowOrchestrator:
    """Headless step-cursor helper (see module docstring; state saving claim removed)."""

    STEP_NAMES = {
        "data_check": "数据校验",
        "factor_map": "单因素图编制",
        "prediction": "地震相预测",
        "map_compile": "古地理图编绘",
        "qc": "质量检查",
        "export": "成果导出",
    }

    def __init__(self, project: ProjectDocument | None = None) -> None:
        self.project = project or ProjectDocument(meta=ProjectMeta(name="Default Project"))
        self.current_step_index = 0
        self.steps = list(STEP_ORDER)

    def get_step_context(self) -> WorkflowStepContext:
        """Deep interface method 1/2: get read-only context of the current active step."""
        if 0 <= self.current_step_index < len(self.steps):
            step_id = self.steps[self.current_step_index]
        else:
            step_id = self.steps[0]

        step_name = self.STEP_NAMES.get(step_id, step_id)
        status = infer_workflow_step_status(self.project, step_id)
        is_valid = status in {"complete", "running", "warning"}

        prereqs = []
        if step_id != "data_check" and not self.project.resources:
            prereqs.append("数据资产清单不能为空")

        return WorkflowStepContext(
            step_id=step_id,
            step_name=step_name,
            index=self.current_step_index,
            total_steps=len(self.steps),
            is_valid=is_valid,
            prerequisites=prereqs,
            status=status,
        )

    def next_step(self, step_payload: dict[str, Any] | None = None) -> StepTransitionResult:
        """Deep interface method 2/2: advance to the next step if prerequisites are satisfied.

        The current step must be evidence-valid (``is_valid``) before
        advancing — an empty project must never walk the whole strip to
        "已完成" without producing anything (audit #847-2).
        """
        ctx = self.get_step_context()
        if ctx.prerequisites:
            return StepTransitionResult(
                success=False,
                message=f"无法进入下一步: {', '.join(ctx.prerequisites)}",
                step_context=ctx,
            )
        if not ctx.is_valid:
            return StepTransitionResult(
                success=False,
                message=f"当前步骤 [{ctx.step_name}] 尚未完成，不能进入下一步",
                step_context=ctx,
            )

        if self.current_step_index < len(self.steps) - 1:
            self.current_step_index += 1
            new_ctx = self.get_step_context()
            return StepTransitionResult(
                success=True,
                message=f"已成功切换至第 {new_ctx.index + 1} 步 [{new_ctx.step_name}]",
                step_context=new_ctx,
            )

        return StepTransitionResult(
            success=True,
            message="工作流已全部完成",
            step_context=ctx,
        )
