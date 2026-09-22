"""Recipe format tests (H4): save/load/clone/rerun-with-new-inputs/migrate/
diff/inspect, and the structural security gate (no secrets, no absolute
write paths, no SQL, no code)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.harness import ActionRegistry, ActionRisk, ActionSpec
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.workflow.dag import (
    NodeSpec,
    SlotSpec,
    WorkflowEngine,
    WorkflowSpec,
)
from paleo_workbench.workflow.dag.store import WorkflowRunStore
from paleo_workbench.workflow.recipe import (
    RecipeDocument,
    RecipeError,
    clone_recipe,
    diff_recipes,
    inspect_recipe,
    load_recipe,
    migrate_recipe,
    recipe_from_run,
    recipe_from_spec,
    save_recipe,
)


def _registry() -> ActionRegistry:
    reg = ActionRegistry()
    for name in ("factor.validate", "factor.interpolate", "map.contour"):
        reg.register(
            ActionSpec(
                action_id=name,
                description=name,
                handler=lambda ctx, p: {"version_ids": []},
                risk=ActionRisk.COMPUTE,
            )
        )
    return reg


def _spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="wf.factor-map",
        name="单因素图",
        description="factor map chain",
        slots=(
            SlotSpec(name="factor", schema={"type": "string"}),
            SlotSpec(name="grid_n", schema={"type": "integer", "minimum": 4}, default=32),
        ),
        nodes=(
            NodeSpec(
                node_id="validate",
                action_id="factor.validate",
                parameters={"factor": {"$slot": "factor"}},
                description="factor QC",
            ),
            NodeSpec(
                node_id="interpolate",
                action_id="factor.interpolate",
                depends_on=("validate",),
                parameters={"factor": {"$slot": "factor"}, "grid_n": {"$slot": "grid_n"}},
            ),
            NodeSpec(
                node_id="contour",
                action_id="map.contour",
                depends_on=("interpolate",),
            ),
        ),
    )


def test_round_trip_save_load(tmp_path):
    recipe = recipe_from_spec(_spec(), tags=("geology", "mapping"))
    path = save_recipe(recipe, tmp_path / "factor.paleo-workflow.json")
    assert path.name.endswith(".paleo-workflow.json")
    loaded = load_recipe(path)
    assert loaded.recipe_id == recipe.recipe_id
    assert loaded.workflow.to_dict() == recipe.workflow.to_dict()
    assert loaded.tags == ("geology", "mapping")


def test_save_appends_recipe_suffix(tmp_path):
    recipe = recipe_from_spec(_spec())
    path = save_recipe(recipe, tmp_path / "factor.json")
    assert path.name == "factor.paleo-workflow.json"


def test_secret_smuggling_refused(tmp_path):
    data = recipe_from_spec(_spec()).to_dict()
    data["workflow"]["nodes"][0]["parameters"]["api_key"] = "sk-xxx"
    with pytest.raises(RecipeError, match="forbidden recipe key"):
        save_recipe(RecipeDocument.from_dict.__func__ if False else _raw(data), tmp_path / "bad.paleo-workflow.json")


def _raw(data):
    from paleo_workbench.workflow.dag.model import WorkflowSpec

    return RecipeDocument(
        recipe_id=data["recipe_id"],
        name=data["name"],
        workflow=WorkflowSpec.from_dict(data["workflow"]),
        schema_version=data["recipe_schema_version"],
    )


def test_absolute_path_refused(tmp_path):
    data = recipe_from_spec(_spec()).to_dict()
    data["workflow"]["nodes"][2]["parameters"]["output_dir"] = "/etc/paleo/out"
    with pytest.raises(RecipeError, match="absolute path"):
        save_recipe(_raw(data), tmp_path / "abs.paleo-workflow.json")


def test_sql_key_refused_on_load(tmp_path):
    data = recipe_from_spec(_spec()).to_dict()
    data["workflow"]["nodes"][0]["parameters"]["sql"] = "DROP TABLE wells"
    path = tmp_path / "sql.paleo-workflow.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecipeError, match="forbidden recipe key"):
        load_recipe(path)


def test_load_refuses_corrupted_json(tmp_path):
    path = tmp_path / "corrupt.paleo-workflow.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(RecipeError, match="not valid JSON"):
        load_recipe(path)


def test_migrate_refuses_unknown_future_version():
    data = recipe_from_spec(_spec()).to_dict()
    data["recipe_schema_version"] = "99.0"
    with pytest.raises(RecipeError, match="newer than this build"):
        migrate_recipe(data)


def test_clone_gets_fresh_identity(tmp_path):
    recipe = recipe_from_spec(_spec())
    clone = clone_recipe(recipe)
    assert clone.recipe_id == f"{recipe.recipe_id}-clone"
    assert clone.source_run_id is None
    assert clone.workflow.to_dict() == recipe.workflow.to_dict()


def test_diff_reports_node_and_param_changes():
    a = recipe_from_spec(_spec())
    modified = clone_recipe(a)
    nodes = list(modified.workflow.nodes)
    nodes[1] = NodeSpec(
        node_id="interpolate",
        action_id="factor.interpolate",
        depends_on=("validate",),
        parameters={"factor": {"$slot": "factor"}, "grid_n": {"$slot": "grid_n"}, "method": "idw"},
    )
    modified.workflow = WorkflowSpec(
        workflow_id=modified.workflow.workflow_id,
        name=modified.workflow.name,
        nodes=tuple(nodes),
        slots=modified.workflow.slots,
    )
    d = diff_recipes(a, modified)
    assert d["nodes_changed"]["interpolate"] == ["parameters"]


def test_inspect_summary_has_no_parameters():
    recipe = recipe_from_spec(_spec())
    summary = inspect_recipe(recipe)
    text = json.dumps(summary, ensure_ascii=False)
    assert "validate" in text and "$slot" not in text.replace("binding", "")


def test_recipe_from_run_bakes_slot_defaults():
    reg = _registry()
    engine = WorkflowEngine(registry=reg, store=WorkflowRunStore(str(Path(__import__("tempfile").mkdtemp()))))
    ctx = ActionContext()
    run = engine.create_run(_spec(), slot_values={"factor": "GR", "grid_n": 64}, context=ctx)
    engine.run(run.run_id, context=ctx)
    recipe = recipe_from_run(engine.store_for(ctx).load(run.run_id))
    slots = {s.name: s for s in recipe.workflow.slots}
    assert slots["factor"].default == "GR"
    assert slots["grid_n"].default == 64
    assert recipe.source_run_id == run.run_id


def test_rerun_with_new_inputs_from_recipe(tmp_path):
    reg = _registry()
    store_root = tmp_path / "runs"
    store_root.mkdir()
    engine = WorkflowEngine(registry=reg, store=WorkflowRunStore(str(store_root)))
    ctx = ActionContext()
    recipe = recipe_from_spec(_spec())
    path = save_recipe(recipe, tmp_path / "wf.paleo-workflow.json", registry=reg)

    loaded = load_recipe(path)
    run = engine.create_run(loaded.workflow, slot_values={"factor": "GR"}, context=ctx)
    first = engine.run(run.run_id, context=ctx)
    assert first.state.value == "completed"

    rerun = engine.rerun(
        first.run_id, slot_overrides={"factor": "RT"}, context=ctx
    )
    assert rerun.state.value == "completed"
    assert rerun.slot_values["factor"] == "RT"
    assert rerun.node_runs["interpolate"].parameters["factor"] == "RT"
