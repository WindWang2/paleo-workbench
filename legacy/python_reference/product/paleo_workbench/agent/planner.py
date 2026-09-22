"""DAG Task Graph Planner for Paleo AI GIS Harness.

Generates dependency graphs and schedules multi-agent execution steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from paleo_workbench.agent.intent import ParsedIntent, TaskDomain


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    id: str
    agent_name: str
    action: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None


@dataclass
class TaskGraph:
    nodes: dict[str, TaskNode] = field(default_factory=dict)

    def add_node(self, node: TaskNode) -> None:
        self.nodes[node.id] = node

    def get_executable_nodes(self) -> list[TaskNode]:
        """Return nodes that are PENDING and whose dependencies are all COMPLETED."""
        ready = []
        for node in self.nodes.values():
            if node.status != TaskStatus.PENDING:
                continue
            deps_ok = all(
                self.nodes[dep_id].status == TaskStatus.COMPLETED
                for dep_id in node.dependencies
                if dep_id in self.nodes
            )
            if deps_ok:
                ready.append(node)
        return ready

    def is_finished(self) -> bool:
        return all(node.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED} for node in self.nodes.values())

    def has_failures(self) -> bool:
        return any(node.status == TaskStatus.FAILED for node in self.nodes.values())


class TaskPlanner:
    """Intelligent DAG Planner that breaks domain intent into multi-agent task steps."""

    def create_plan(self, intent: ParsedIntent) -> TaskGraph:
        graph = TaskGraph()

        # Step 1: Data Discovery & Inspection (Always First)
        graph.add_node(
            TaskNode(
                id="task_data_discover",
                agent_name="data_agent",
                action="discover_and_validate",
                description="Discover and validate catalog data assets and schemas",
                dependencies=[],
                parameters=intent.parameters,
            )
        )

        # Step 2: Domain-specific Processing
        if intent.primary_domain in {TaskDomain.WELL_LOGGING, TaskDomain.SINGLE_FACTOR_MAPPING, TaskDomain.PALEOMAP_COMPILATION}:
            graph.add_node(
                TaskNode(
                    id="task_well_process",
                    agent_name="well_agent",
                    action="process_well_tops_and_curves",
                    description="Extract formation tops and align well log curves",
                    dependencies=["task_data_discover"],
                    parameters=intent.parameters,
                )
            )

        if intent.primary_domain in {TaskDomain.SEISMIC_INTERPRETATION, TaskDomain.PALEOMAP_COMPILATION}:
            graph.add_node(
                TaskNode(
                    id="task_seismic_process",
                    agent_name="seismic_agent",
                    action="extract_slices_and_attributes",
                    description="Extract 3D seismic slices and coherence volumes",
                    dependencies=["task_data_discover"],
                    parameters=intent.parameters,
                )
            )

        # Step 3: Spatial & GIS Analysis
        graph.add_node(
            TaskNode(
                id="task_gis_spatial",
                agent_name="gis_agent",
                action="analyze_spatial_constraints",
                description="Extract fault barriers and validate boundary topologies",
                dependencies=["task_data_discover"],
                parameters=intent.parameters,
            )
        )

        # Step 4: Single-Factor / Paleomap Cartography
        carto_deps = ["task_gis_spatial"]
        if "task_well_process" in graph.nodes:
            carto_deps.append("task_well_process")
        if "task_seismic_process" in graph.nodes:
            carto_deps.append("task_seismic_process")

        graph.add_node(
            TaskNode(
                id="task_carto_generate",
                agent_name="carto_agent",
                action="generate_factor_surface",
                description="Perform barrier-constrained anisotropic IDW and contouring",
                dependencies=carto_deps,
                parameters=intent.parameters,
            )
        )

        # Step 5: Map Composition & Visualization
        graph.add_node(
            TaskNode(
                id="task_viz_compose",
                agent_name="viz_agent",
                action="compose_map_layout",
                description="Compose standardized geological map layout with legends and graticules",
                dependencies=["task_carto_generate"],
                parameters=intent.parameters,
            )
        )

        # Step 6: QA / QC Verification
        graph.add_node(
            TaskNode(
                id="task_qa_audit",
                agent_name="qa_agent",
                action="audit_and_verify",
                description="Execute topological, boundary, and statistical QC audit",
                dependencies=["task_viz_compose"],
                parameters=intent.parameters,
            )
        )

        # Step 7: Final Delivery & Result Reporting
        graph.add_node(
            TaskNode(
                id="task_result_delivery",
                agent_name="result_agent",
                action="package_and_report",
                description="Assemble execution report, lineage metadata, and deliverables",
                dependencies=["task_qa_audit"],
                parameters=intent.parameters,
            )
        )

        return graph


task_planner = TaskPlanner()
