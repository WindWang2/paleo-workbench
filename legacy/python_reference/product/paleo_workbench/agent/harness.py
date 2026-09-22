"""Paleo AI GIS Harness: Master Autonomous Multi-Agent Orchestrator."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.agent.agents.base import BaseAgent
from paleo_workbench.agent.agents.data_agent import DataAgent
from paleo_workbench.agent.agents.well_agent import WellAgent
from paleo_workbench.agent.agents.seismic_agent import SeismicAgent
from paleo_workbench.agent.agents.gis_agent import GISAgent
from paleo_workbench.agent.agents.carto_agent import CartographyAgent
from paleo_workbench.agent.agents.viz_agent import VisualizationAgent
from paleo_workbench.agent.agents.qa_agent import QAAgent
from paleo_workbench.agent.agents.result_agent import ResultAgent
from paleo_workbench.agent.intent import IntentParser, ParsedIntent, intent_parser
from paleo_workbench.agent.planner import TaskGraph, TaskNode, TaskPlanner, TaskStatus, task_planner
from paleo_workbench.agent.registries.tool_registry import tool_registry
from paleo_workbench.agent.registries.skill_registry import skill_registry
from paleo_workbench.agent.registries.algorithm_registry import algorithm_registry
from paleo_workbench.agent.registries.template_registry import template_registry

_LOG = logging.getLogger("paleo_workbench.agent.harness")


@dataclass
class HarnessExecutionResult:
    query: str
    intent: ParsedIntent
    plan: TaskGraph
    success: bool
    execution_time_sec: float
    deliverables: dict[str, Any] = field(default_factory=dict)
    execution_logs: list[str] = field(default_factory=list)


class PaleoAIHarness:
    """Industrial Autonomous AI Harness orchestrating the 8-Agent GIS Swarm."""

    def __init__(
        self,
        parser: IntentParser | None = None,
        planner: TaskPlanner | None = None,
    ) -> None:
        self.parser = parser or intent_parser
        self.planner = planner or task_planner
        self.agents: dict[str, BaseAgent] = {
            "data_agent": DataAgent(),
            "well_agent": WellAgent(),
            "seismic_agent": SeismicAgent(),
            "gis_agent": GISAgent(),
            "carto_agent": CartographyAgent(),
            "viz_agent": VisualizationAgent(),
            "qa_agent": QAAgent(),
            "result_agent": ResultAgent(),
        }
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.algorithm_registry = algorithm_registry
        self.template_registry = template_registry

    def execute_query(
        self,
        user_query: str,
        context: dict[str, Any] | None = None,
    ) -> HarnessExecutionResult:
        """End-to-end execution of a user query through Intent -> Planner -> Multi-Agent Swarm."""
        start_time = time.perf_counter()
        logs: list[str] = []

        def _log(msg: str) -> None:
            _LOG.info(msg)
            logs.append(msg)

        _log(f"Starting AI Harness for query: '{user_query}'")

        # 1. Intent Parsing
        intent = self.parser.parse(user_query, context)
        _log(f"Parsed Intent: Primary Domain='{intent.primary_domain.value}', Target Horizon='{intent.target_horizon}', Factor='{intent.factor_type}'")

        # 2. Task Graph Planning
        plan = self.planner.create_plan(intent)
        _log(f"Generated Task Graph with {len(plan.nodes)} execution nodes.")

        exec_context = dict(intent.parameters)
        if context:
            exec_context.update(context)

        # 3. Autonomous Execution Loop
        max_iterations = 20
        iteration = 0

        while not plan.is_finished() and iteration < max_iterations:
            iteration += 1
            ready_nodes = plan.get_executable_nodes()
            if not ready_nodes:
                break

            for node in ready_nodes:
                node.status = TaskStatus.RUNNING
                agent = self.agents.get(node.agent_name)
                _log(f"[Iteration {iteration}] Dispatching task '{node.id}' to agent '{node.agent_name}'")

                if agent is None:
                    node.status = TaskStatus.FAILED
                    node.error = f"Agent '{node.agent_name}' not found."
                    _log(f"ERROR: {node.error}")
                    continue

                try:
                    res = agent.run(node, exec_context)
                    node.result = res
                    node.status = TaskStatus.COMPLETED
                    exec_context[f"{node.id}_result"] = res
                    _log(f"Task '{node.id}' completed successfully.")
                except Exception as exc:
                    node.status = TaskStatus.FAILED
                    node.error = str(exc)
                    _log(f"Task '{node.id}' failed with exception: {exc}")

        elapsed = time.perf_counter() - start_time
        success = not plan.has_failures() and plan.is_finished()
        _log(f"Harness execution completed in {elapsed:.3f}s. Overall status: {'SUCCESS' if success else 'FAILED'}")

        # Extract final deliverable from result agent node
        deliverables = {}
        if "task_result_delivery" in plan.nodes and plan.nodes["task_result_delivery"].result:
            deliverables = plan.nodes["task_result_delivery"].result

        return HarnessExecutionResult(
            query=user_query,
            intent=intent,
            plan=plan,
            success=success,
            execution_time_sec=elapsed,
            deliverables=deliverables,
            execution_logs=logs,
        )


# Global default Harness
harness = PaleoAIHarness()
