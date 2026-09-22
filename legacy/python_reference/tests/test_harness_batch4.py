"""Unit tests for Batch 4: Paleo AI GIS Harness, Registries & Multi-Agent Swarm."""

import pytest

from paleo_workbench.agent import (
    PaleoAIHarness,
    TaskDomain,
    algorithm_registry,
    harness,
    intent_parser,
    skill_registry,
    task_planner,
    template_registry,
    tool_registry,
)
from paleo_workbench.agent.registries import ToolParameter


def test_tool_registry_registration_and_execution():
    reg = tool_registry

    @reg.register(
        name="test_math_multiply",
        description="Multiply two numbers",
        category="math",
        parameters=[
            ToolParameter("a", "number", "first factor"),
            ToolParameter("b", "number", "second factor"),
        ],
    )
    def multiply(a: float, b: float) -> float:
        return a * b

    tool = reg.get_tool("test_math_multiply")
    assert tool is not None
    assert tool.name == "test_math_multiply"

    # Schema export
    schema = tool.to_schema()
    assert schema["name"] == "test_math_multiply"
    assert "parameters" in schema

    # Execution
    res = reg.execute("test_math_multiply", a=3.5, b=2.0)
    assert res == 7.0


def test_tool_registry_rejects_bad_calls_and_hijack():
    """#1185: unknown kwargs / missing required / type mismatch refused;
    same-name re-registration raises unless identical handler."""
    from paleo_workbench.agent.registries.tool_registry import (
        DuplicateToolError,
        ToolRegistry,
        ToolValidationError,
    )

    reg = ToolRegistry()

    @reg.register(
        name="t1185_add",
        description="add",
        parameters=[
            ToolParameter("a", "number", "x"),
            ToolParameter("b", "number", "y"),
        ],
    )
    def _add(a: float, b: float) -> float:
        return a + b

    assert reg.execute("t1185_add", a=1.0, b=2.0) == 3.0
    with pytest.raises(ToolValidationError):
        reg.execute("t1185_add", a=1.0, b=2.0, evil="x")
    with pytest.raises(ToolValidationError):
        reg.execute("t1185_add", a=1.0)
    with pytest.raises(ToolValidationError):
        reg.execute("t1185_add", a="1", b=2.0)
    with pytest.raises(KeyError):
        reg.execute("t1185_missing")

    @reg.register(
        name="t1185_hijack",
        description="first",
        parameters=[ToolParameter("a", "number", "x")],
    )
    def _first(a: float) -> float:
        return a

    # Same handler object re-registered: idempotent, no raise.
    reg.register(
        name="t1185_hijack",
        description="first again",
        parameters=[ToolParameter("a", "number", "x")],
    )(_first)
    assert reg.execute("t1185_hijack", a=1.0) == 1.0

    @reg.register(
        name="t1185_victim",
        description="victim",
        parameters=[ToolParameter("a", "number", "x")],
    )
    def _victim(a: float) -> float:
        return a

    def _impostor(a: float) -> float:
        return -a

    with pytest.raises(DuplicateToolError):
        reg.register(
            name="t1185_victim",
            description="impostor",
            parameters=[ToolParameter("a", "number", "x")],
        )(_impostor)
    # Victim intact after the refused hijack.
    assert reg.execute("t1185_victim", a=2.0) == 2.0


# ------------------------------------------------- #1185 registry hygiene --
def test_tool_registry_rejects_duplicate_names():
    from paleo_workbench.agent.registries import ToolRegistry

    reg = ToolRegistry()

    @reg.register(name="dup_tool", description="first")
    def first():
        return 1

    with pytest.raises(ValueError, match="already registered"):

        @reg.register(name="dup_tool", description="second")
        def second():
            return 2

    assert reg.execute("dup_tool") == 1  # original registration kept


def test_tool_registry_execute_validates_required_parameters():
    from paleo_workbench.agent.registries import ToolRegistry

    reg = ToolRegistry()

    @reg.register(
        name="needs_args",
        description="requires arguments",
        parameters=[
            ToolParameter("a", "number", "required"),
            ToolParameter("b", "number", "optional", required=False, default=0.0),
        ],
    )
    def add(a: float, b: float = 0.0) -> float:
        return a + b

    with pytest.raises(TypeError, match="missing required parameter"):
        reg.execute("needs_args")  # 'a' missing
    assert reg.execute("needs_args", a=1.0, b=2.0) == 3.0
    assert reg.execute("needs_args", a=1.0) == 1.0  # optional default applies


def test_skill_registry_rejects_duplicate_names():
    from paleo_workbench.agent.registries import SkillRegistry

    reg = SkillRegistry()

    @reg.register(name="dup_skill", description="first")
    def first(context, **kwargs):
        return 1

    with pytest.raises(ValueError, match="already registered"):

        @reg.register(name="dup_skill", description="second")
        def second(context, **kwargs):
            return 2

    assert reg.execute_skill("dup_skill", {}) == 1


def test_algorithm_registry_rejects_duplicate_ids():
    from paleo_workbench.agent.registries import AlgorithmMetadata, AlgorithmRegistry

    reg = AlgorithmRegistry()
    metadata = AlgorithmMetadata(
        id="dup_algo",
        name="Dup",
        category="test",
        description="d",
        time_complexity="O(1)",
        space_complexity="O(1)",
        has_cpp_accel=False,
        supports_gpu=False,
    )
    reg.register(metadata)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(metadata)
    assert reg.get("dup_algo") is metadata


def test_template_registry_rejects_duplicate_layout_ids():
    from paleo_workbench.agent.registries import MapLayoutTemplate, TemplateRegistry

    reg = TemplateRegistry()
    template = MapLayoutTemplate(
        id="dup_layout",
        name="Dup",
        paper_size="A4",
        orientation="landscape",
        margins_mm=(10.0, 10.0, 10.0, 10.0),
    )
    reg.register_layout(template)
    with pytest.raises(ValueError, match="already registered"):
        reg.register_layout(template)
    assert reg.get_layout("dup_layout") is template


def test_algorithm_and_template_registries():
    # Algorithm
    algo = algorithm_registry.get("dtw_curve_matcher")
    assert algo is not None
    assert algo.time_complexity == "O(N * M)"
    assert algo.has_cpp_accel is True

    # Template
    layout = template_registry.get_layout("a4_landscape_standard")
    assert layout is not None
    assert layout.paper_size == "A4"
    assert layout.include_legend is True

    palette = template_registry.get_palette("geological_lithology")
    assert len(palette) > 0


def test_intent_parser():
    query = "分析川西须家河组各井砂地比空间分布并生成单因素图"
    intent = intent_parser.parse(query)

    assert intent.primary_domain in {TaskDomain.SINGLE_FACTOR_MAPPING, TaskDomain.WELL_LOGGING}
    assert "须家河组" in intent.target_horizon or intent.target_horizon != ""
    assert intent.factor_type == "sand_ratio"
    assert len(intent.suggested_skills) > 0


def test_task_planner_dag_generation():
    query = "须家河组砂地比单因素图编制与质检"
    intent = intent_parser.parse(query)
    plan = task_planner.create_plan(intent)

    assert len(plan.nodes) >= 5
    assert "task_data_discover" in plan.nodes
    assert "task_carto_generate" in plan.nodes
    assert "task_qa_audit" in plan.nodes

    # Check executable nodes (initially only root nodes with no dependencies)
    ready = plan.get_executable_nodes()
    assert len(ready) == 1
    assert ready[0].id == "task_data_discover"


def test_full_autonomous_harness_execution():
    query = "对须家河组一段测井数据进行对齐，生成砂地比单因素图并完成编图与质检"
    res = harness.execute_query(query)

    assert res.success is True
    assert res.plan.is_finished() is True
    assert not res.plan.has_failures()
    assert res.execution_time_sec >= 0.0
    assert len(res.execution_logs) > 0
    assert "task_result_delivery" in res.plan.nodes
    assert res.deliverables.get("status") == "success"
