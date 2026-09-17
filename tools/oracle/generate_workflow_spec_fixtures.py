#!/usr/bin/env python3
"""Oracle fixture generator for the C++ workflow_spec kernel (CONV-06).

Imports the REAL implementations (paleo_workbench.workflow.dag.model,
paleo_workbench.workflow.dag.validation, paleo_workbench.harness.registry,
paleo_workbench.providers.execution) and freezes their verdicts, problem
messages and canonical hashes to JSON so the C++ port in libs/workflow_spec
can be reconciled message-for-message. Regenerate with:

    python3 tools/oracle/generate_workflow_spec_fixtures.py

Every expectation below is COMPUTED by running the real Python functions —
no hand-written verdicts. The single exception path is the DESTRUCTIVE-risk
case: the production ActionRegistry refuses to register destructive actions
(pragma-no-cover branch in validate_workflow_spec), so the generator drives
the real validate_workflow_spec through a duck-typed registry holding a real
ActionSpec with risk=DESTRUCTIVE (construction is allowed; registration is
what is refused).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.harness.registry import ActionRegistry, ActionRisk, ActionSpec  # noqa: E402
from paleo_workbench.providers.execution import validate_parameters  # noqa: E402
from paleo_workbench.workflow.dag import model as dag_model  # noqa: E402
from paleo_workbench.workflow.dag import validation as dag_validation  # noqa: E402
from paleo_workbench.workflow.dag.model import (  # noqa: E402
    NodeCondition,
    NodeRun,
    NodeSpec,
    NodeState,
    RetryPolicy,
    RunState,
    SlotSpec,
    WorkflowRun,
    WorkflowSpec,
)
from paleo_workbench.workflow.dag.validation import (  # noqa: E402
    BindingError,
    bind_parameters,
    materialize_slot_defaults,
    resolve_value,
    slot_schema_problems,
    validate_condition_tree,
    validate_workflow_spec,
)

OUT = REPO_ROOT / "libs" / "workflow_spec" / "workflow_spec_tests" / "fixtures"

ACTION_IDS = (
    "a.compute", "b.compute", "c.compute", "d.compute",
    "factor.validate", "factor.interpolate", "map.contour", "workflow.run",
)


def build_registry() -> ActionRegistry:
    reg = ActionRegistry()
    for name in ACTION_IDS:
        reg.register(ActionSpec(
            action_id=name,
            description=f"{name} oracle action",
            handler=lambda ctx, p: {},
            risk=ActionRisk.COMPUTE,
        ))
    return reg


def registry_map(reg: ActionRegistry) -> dict[str, str]:
    return {s.action_id: s.risk.value for s in reg.specs()}


def spec_of(**kwargs) -> WorkflowSpec:
    kwargs.setdefault("workflow_id", "wf.oracle")
    kwargs.setdefault("name", "oracle")
    return WorkflowSpec(**kwargs)


def node(node_id, action_id, *, depends_on=(), parameters=None, condition=None,
         retry=None, description="") -> NodeSpec:
    return NodeSpec(
        node_id=node_id, action_id=action_id,
        parameters=parameters or {}, depends_on=tuple(depends_on),
        condition=condition, retry=retry or RetryPolicy(),
        description=description,
    )


# ----------------------------------------------------------------- cases --


def valid_spec_cases() -> list[dict]:
    cases: list[dict] = []
    reg = build_registry()
    rmap = registry_map(reg)

    def add(name: str, spec: WorkflowSpec, registry=rmap) -> None:
        problems = validate_workflow_spec(spec, _DuckOrRealRegistry(spec, registry))
        assert not problems, (name, problems)
        cases.append({
            "name": name,
            "registry": registry,
            "spec": spec.to_dict(),
            "reserialized": WorkflowSpec.from_dict(spec.to_dict()).to_dict(),
            "spec_hash": dag_model.canonical_hash(spec.to_dict()),
        })

    add("linear3", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",)),
        node("c", "c.compute", depends_on=("b",)),
    )))
    add("diamond4", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",)),
        node("c", "c.compute", depends_on=("a",)),
        node("d", "d.compute", depends_on=("b", "c")),
    )))
    add("parallel_max_concurrency", spec_of(workflow_id="wf.par", name="par",
        max_concurrency=2, nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",)),
        node("c", "c.compute", depends_on=("a",)),
    )))
    add("recipe_chinese_factor_map", WorkflowSpec(
        workflow_id="wf.factor-map", name="单因素图",
        description="factor map chain",
        slots=(
            SlotSpec(name="factor", schema={"type": "string"}),
            SlotSpec(name="grid_n", schema={"type": "integer", "minimum": 4}, default=32),
        ),
        nodes=(
            node("validate", "factor.validate", parameters={"factor": {"$slot": "factor"}},
                 description="factor QC"),
            node("interpolate", "factor.interpolate", depends_on=("validate",),
                 parameters={"factor": {"$slot": "factor"}, "grid_n": {"$slot": "grid_n"}}),
            node("contour", "map.contour", depends_on=("interpolate",)),
        ),
    ))
    add("ref_without_key", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",), parameters={"up": {"$ref": "a"}}),
    )))
    add("ref_with_key", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             parameters={"version": {"$ref": "a", "key": "version_id"}}),
    )))
    add("slot_nested_containers", spec_of(slots=(SlotSpec(name="factor"),), nodes=(
        node("a", "a.compute", parameters={
            "opts": {"factor": {"$slot": "factor"}, "tags": [{"$slot": "factor"}, "static"]},
        }),
    )))
    add("context_workspace", spec_of(nodes=(
        node("a", "a.compute", parameters={"w": {"$context": "workspace_id"}}),
    )))
    add("context_selection_dotted", spec_of(nodes=(
        node("a", "a.compute",
             parameters={"wells": {"$context": "selection.selected_well_ids"}}),
    )))
    add("condition_node_succeeded", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(kind="node_succeeded", node="a")),
    )))
    add("condition_node_output_equals", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(kind="node_output_equals", node="a", key="mode",
                                     value="full")),
    )))
    add("condition_node_state", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(kind="node_state", node="a", state="succeeded")),
    )))
    add("condition_all_of", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(kind="all_of", conditions=(
                 NodeCondition(kind="node_succeeded", node="a"),
                 NodeCondition(kind="node_output_equals", node="a", key="ok", value=True),
             ))),
    )))
    add("condition_any_of", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(kind="any_of", conditions=(
                 NodeCondition(kind="node_succeeded", node="a"),
             ))),
    )))
    add("condition_not", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(
                 kind="not",
                 condition=NodeCondition(kind="node_succeeded", node="a"))),
    )))
    add("condition_deep_nest", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(kind="all_of", conditions=(
                 NodeCondition(kind="any_of", conditions=(
                     NodeCondition(kind="node_succeeded", node="a"),
                     NodeCondition(kind="not", condition=NodeCondition(
                         kind="node_state", node="a", state="failed")),
                 )),
             ))),
    )))
    add("retry_custom", spec_of(nodes=(
        node("a", "a.compute", retry=RetryPolicy(max_attempts=5, backoff_seconds=2.5)),
    )))
    add("unicode_name_and_desc", spec_of(
        workflow_id="wf.corr-map-1", name="连井对比 & 编图",
        description="层位 T2 → 单因素 → 古地理图",
        nodes=(node("a", "a.compute", description="输入检查"),),
    ))
    add("workflow_id_max_boundary", spec_of(
        workflow_id="a" * 2 + "." + "b" * 60, name="boundary",
        nodes=(node("a", "a.compute"),),
    ))
    add("workflow_id_trailing_newline", spec_of(
        workflow_id="ab\n", name="newline",
        nodes=(node("a", "a.compute"),),
    ))
    add("condition_state_and_value_order", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             condition=NodeCondition(kind="node_state", node="a",
                                     state="failed", value=2.5)),
    )))
    add("empty_depends_and_params", spec_of(nodes=(
        node("a", "a.compute", depends_on=(), parameters={}),
    )))
    add("slot_optional_no_default", spec_of(slots=(
        SlotSpec(name="opt", required=False),
    ), nodes=(node("a", "a.compute"),)))
    add("slot_default_types", spec_of(slots=(
        SlotSpec(name="s", default="文本"),
        SlotSpec(name="i", schema={"type": "integer"}, default=7),
        SlotSpec(name="f", schema={"type": "number"}, default=0.5),
        SlotSpec(name="b", schema={"type": "boolean"}, default=False),
    ), nodes=(node("a", "a.compute"),)))

    raw_defaults = {
        "workflow_id": "wf.raw",
        "name": "raw",
        "nodes": [{"node_id": "a", "action_id": "a.compute"}],
    }
    problems = validate_workflow_spec(
        WorkflowSpec.from_dict(raw_defaults), reg)
    assert not problems, problems
    cases.append({
        "name": "raw_dict_defaults",
        "registry": rmap,
        "spec": raw_defaults,
        "reserialized": WorkflowSpec.from_dict(raw_defaults).to_dict(),
        "spec_hash": dag_model.canonical_hash(WorkflowSpec.from_dict(raw_defaults).to_dict()),
    })

    raw_slot = {
        "workflow_id": "wf.rawslot",
        "name": "rawslot",
        "slots": [{"name": "factor"}],
        "nodes": [{"node_id": "a", "action_id": "a.compute",
                   "parameters": {"f": {"$slot": "factor"}}}],
    }
    raw_falsy = {
        "workflow_id": "wf.falsy",
        "name": "falsy",
        "schema_version": "",
        "nodes": [{"node_id": "a", "action_id": "a.compute",
                   "parameters": []}],
        "slots": [{"name": "opt", "required": 0}],
    }
    falsy_spec = WorkflowSpec.from_dict(raw_falsy)
    problems = validate_workflow_spec(falsy_spec, reg)
    assert not problems, problems
    cases.append({
        "name": "raw_dict_falsy_containers",
        "registry": rmap,
        "spec": raw_falsy,
        "reserialized": WorkflowSpec.from_dict(raw_falsy).to_dict(),
        "spec_hash": dag_model.canonical_hash(WorkflowSpec.from_dict(raw_falsy).to_dict()),
    })

    problems = validate_workflow_spec(
        WorkflowSpec.from_dict(raw_slot), reg)
    assert not problems, problems
    cases.append({
        "name": "raw_dict_slot_schema_fallback",
        "registry": rmap,
        "spec": raw_slot,
        "reserialized": WorkflowSpec.from_dict(raw_slot).to_dict(),
        "spec_hash": dag_model.canonical_hash(WorkflowSpec.from_dict(raw_slot).to_dict()),
    })
    return cases


class _DuckOrRealRegistry:
    """Real ActionRegistry when the map came from one; duck-typed shim for the
    DESTRUCTIVE case (production registration refuses destructive)."""

    def __init__(self, spec: WorkflowSpec, registry: dict[str, str]) -> None:
        self._map = registry
        self._spec = spec

    def get(self, action_id: str):
        risk = self._map.get(action_id)
        if risk is None:
            raise LookupError(action_id)
        if risk == "destructive":
            return ActionSpec(action_id=action_id, description="destructive",
                              handler=lambda c, p: {}, risk=ActionRisk.DESTRUCTIVE)
        return ActionSpec(action_id=action_id, description="shim",
                          handler=lambda c, p: {}, risk=ActionRisk(risk))


def invalid_spec_cases() -> list[dict]:
    cases: list[dict] = []
    reg = build_registry()
    rmap = registry_map(reg)

    def add(name: str, spec: WorkflowSpec, registry=rmap) -> None:
        problems = validate_workflow_spec(spec, _DuckOrRealRegistry(spec, registry))
        assert problems, name
        cases.append({
            "name": name,
            "registry": registry,
            "spec": spec.to_dict(),
            "problems": problems,
        })

    def add_raw(name: str, raw: dict, registry=rmap) -> None:
        spec = WorkflowSpec.from_dict(raw)
        problems = validate_workflow_spec(spec, _DuckOrRealRegistry(spec, registry))
        assert problems, name
        cases.append({
            "name": name,
            "registry": registry,
            "spec": raw,
            "problems": problems,
        })

    add("empty_workflow_id", spec_of(workflow_id="",
                                     nodes=(node("a", "a.compute"),)))
    add("uppercase_workflow_id", spec_of(workflow_id="WF.X",
                                         nodes=(node("a", "a.compute"),)))
    add("workflow_id_too_long", spec_of(workflow_id="a" * 65,
                                        nodes=(node("a", "a.compute"),)))
    add("workflow_id_bad_char", spec_of(workflow_id="bad space",
                                        nodes=(node("a", "a.compute"),)))
    add("workflow_id_single_char", spec_of(workflow_id="a",
                                           nodes=(node("a", "a.compute"),)))
    add("no_nodes", spec_of(nodes=()))
    add("max_concurrency_zero", spec_of(max_concurrency=0,
                                        nodes=(node("a", "a.compute"),)))
    add("max_concurrency_negative", spec_of(max_concurrency=-3,
                                            nodes=(node("a", "a.compute"),)))
    add("node_id_uppercase", spec_of(nodes=(node("Node", "a.compute"),)))
    add("node_id_digit_start", spec_of(nodes=(node("9node", "a.compute"),)))
    add("node_id_empty", spec_of(nodes=(node("", "a.compute"),)))
    add("duplicate_node_id", spec_of(nodes=(
        node("a", "a.compute"),
        node("a", "b.compute"),
    )))
    add("duplicate_node_id_skips_action_check", spec_of(nodes=(
        node("a", "a.compute"),
        node("a", "ghost.action"),
    )))
    add("duplicate_bad_node_id", spec_of(nodes=(
        node("Bad", "a.compute"),
        node("Bad", "b.compute"),
    )))
    add("unknown_action", spec_of(nodes=(node("a", "ghost.action"),)))
    add("meta_workflow_action", spec_of(nodes=(node("a", "workflow.run"),)))
    destructive_map = dict(rmap)
    destructive_map["x.destroy"] = "destructive"
    add("destructive_action_and_retry_zero", spec_of(nodes=(
        node("a", "x.destroy", retry=RetryPolicy(max_attempts=0)),
    )), registry=destructive_map)
    add("retry_max_attempts_zero", spec_of(nodes=(
        node("a", "a.compute", retry=RetryPolicy(max_attempts=0)),
    )))
    add("condition_unknown_kind", spec_of(nodes=(
        node("a", "a.compute", condition=NodeCondition(kind="bogus")),
    )))
    add("condition_missing_node", spec_of(nodes=(
        node("a", "a.compute",
             condition=NodeCondition(kind="node_succeeded")),
    )))
    add("condition_output_equals_missing_key", spec_of(nodes=(
        node("a", "a.compute",
             condition=NodeCondition(kind="node_output_equals", node="a")),
    )))
    add("condition_state_missing_state", spec_of(nodes=(
        node("a", "a.compute",
             condition=NodeCondition(kind="node_state", node="a")),
    )))
    add("condition_all_of_empty", spec_of(nodes=(
        node("a", "a.compute",
             condition=NodeCondition(kind="all_of", conditions=())),
    )))
    add("condition_not_missing_child", spec_of(nodes=(
        node("a", "a.compute", condition=NodeCondition(kind="not")),
    )))
    add("condition_nested_errors", spec_of(nodes=(
        node("a", "a.compute", condition=NodeCondition(kind="all_of", conditions=(
            NodeCondition(kind="not"),
            NodeCondition(kind="bogus"),
        ))),
    )))
    add("bad_slot_name", spec_of(slots=(SlotSpec(name="9bad"),),
                                 nodes=(node("a", "a.compute"),)))
    add("slot_name_uppercase", spec_of(slots=(SlotSpec(name="Factor"),),
                                       nodes=(node("a", "a.compute"),)))
    add("duplicate_slot_names", spec_of(slots=(
        SlotSpec(name="x"), SlotSpec(name="x"),
    ), nodes=(node("a", "a.compute"),)))
    add("missing_dependency", spec_of(nodes=(
        node("a", "a.compute", depends_on=("ghost",)),
    )))
    add("self_dependency", spec_of(nodes=(
        node("a", "a.compute", depends_on=("a",)),
    )))
    add("condition_references_unknown_node", spec_of(nodes=(
        node("a", "a.compute",
             condition=NodeCondition(kind="node_succeeded", node="ghost")),
    )))
    add("slot_binding_unknown", spec_of(nodes=(
        node("a", "a.compute", parameters={"s": {"$slot": "nope"}}),
    )))
    add("slot_binding_non_string", spec_of(nodes=(
        node("a", "a.compute", parameters={"s": {"$slot": 3}}),
    )))
    add("ref_unknown_node", spec_of(nodes=(
        node("a", "a.compute", parameters={"up": {"$ref": "ghost"}}),
    )))
    add("ref_not_in_depends_on", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", parameters={"up": {"$ref": "a"}}),
    )))
    add("ref_key_non_string", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             parameters={"up": {"$ref": "a", "key": 3}}),
    )))
    add("context_not_whitelisted", spec_of(nodes=(
        node("a", "a.compute",
             parameters={"x": {"$context": "project.meta.secret"}}),
    )))
    add("context_non_string", spec_of(nodes=(
        node("a", "a.compute", parameters={"x": {"$context": 1}}),
    )))
    add("binding_mixed_keys_slot", spec_of(nodes=(
        node("a", "a.compute", parameters={"s": {"$slot": "factor", "extra": 1}}),
    )))
    add("binding_mixed_keys_ref", spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",),
             parameters={"up": {"$ref": "a", "extra": 1}}),
    )))
    add("binding_mixed_keys_deep", spec_of(nodes=(
        node("a", "a.compute", parameters={
            "list": [{"ok": 1}, {"$ref": "a", "$slot": "x"}]}),
    )))
    add("cycle_two_nodes", spec_of(nodes=(
        node("a", "a.compute", depends_on=("b",)),
        node("b", "b.compute", depends_on=("a",)),
    )))
    add("cycle_three_with_downstream_tail", spec_of(nodes=(
        node("a", "a.compute", depends_on=("c",)),
        node("b", "b.compute", depends_on=("a",)),
        node("c", "c.compute", depends_on=("b",)),
        node("d", "d.compute", depends_on=("a",)),
    )))
    add("duplicate_id_with_cycle", spec_of(nodes=(
        node("a", "a.compute", depends_on=("b",)),
        node("a", "b.compute"),
        node("b", "b.compute", depends_on=("a",)),
    )))
    add("multi_problem_head", spec_of(workflow_id="", max_concurrency=0, nodes=()))
    add_raw("raw_dict_missing_action_key", {
        "workflow_id": "wf.bad",
        "name": "bad",
        "nodes": [{"node_id": "a", "action_id": "ghost.action",
                   "depends_on": ["ghost2"], "retry": {"max_attempts": 0}}],
    })
    return cases


def condition_tree_cases() -> list[dict]:
    cases: list[dict] = []
    tree_cases = [
        ("valid_node_succeeded", NodeCondition(kind="node_succeeded", node="a")),
        ("valid_output_equals", NodeCondition(
            kind="node_output_equals", node="a", key="k", value=1)),
        ("valid_node_state", NodeCondition(kind="node_state", node="a", state="failed")),
        ("valid_all_of", NodeCondition(kind="all_of", conditions=(
            NodeCondition(kind="node_succeeded", node="a"),
            NodeCondition(kind="node_succeeded", node="b")))),
        ("truthy_empty_node", NodeCondition(kind="node_succeeded", node="")),
        ("truthy_empty_key", NodeCondition(
            kind="node_output_equals", node="a", key="")),
        ("truthy_empty_state", NodeCondition(
            kind="node_state", node="a", state="")),
        ("unknown_empty_kind", NodeCondition(kind="")),
        ("invalid_unknown_kind", NodeCondition(kind="sometimes")),
        ("invalid_missing_node", NodeCondition(kind="node_succeeded")),
        ("invalid_missing_key", NodeCondition(kind="node_output_equals", node="a")),
        ("invalid_missing_state", NodeCondition(kind="node_state", node="a")),
        ("invalid_all_of_empty", NodeCondition(kind="all_of", conditions=())),
        ("invalid_any_of_empty", NodeCondition(kind="any_of", conditions=())),
        ("invalid_not_missing_child", NodeCondition(kind="not")),
        ("nested_errors", NodeCondition(kind="all_of", conditions=(
            NodeCondition(kind="not"),
            NodeCondition(kind="node_output_equals", node="a"),
            NodeCondition(kind="meh"),
        ))),
        ("nested_deep_valid", NodeCondition(kind="all_of", conditions=(
            NodeCondition(kind="any_of", conditions=(
                NodeCondition(kind="node_succeeded", node="a"),
                NodeCondition(kind="not", condition=NodeCondition(
                    kind="node_state", node="a", state="cancelled")))),
            NodeCondition(kind="node_output_equals", node="b", key="n", value=2.5),
        ))),
    ]
    for name, cond in tree_cases:
        cases.append({
            "name": name,
            "condition": cond.to_dict(),
            "problems": validate_condition_tree(cond),
        })
    return cases


def slot_binding_cases() -> list[dict]:
    cases: list[dict] = []

    def add(name, slots, slot_values, *, workflow_id="wf.slots"):
        spec = spec_of(workflow_id=workflow_id, name="slots",
                       slots=slots, nodes=(node("a", "a.compute"),))
        materialized = materialize_slot_defaults(spec, dict(slot_values))
        cases.append({
            "name": name,
            "spec": spec.to_dict(),
            "slot_values": slot_values,
            "materialized": materialized,
            "problems": slot_schema_problems(spec, materialized),
        })

    add("required_missing", (SlotSpec(name="factor"),), {})
    add("unknown_slot", (SlotSpec(name="factor"),), {"ghost": 1})
    add("string_ok", (SlotSpec(name="factor"),), {"factor": "GR"})
    add("integer_got_string",
        (SlotSpec(name="grid_n", schema={"type": "integer"}),),
        {"grid_n": "big"})
    add("integer_below_minimum",
        (SlotSpec(name="grid_n", schema={"type": "integer", "minimum": 4}),),
        {"grid_n": 2})
    add("number_above_maximum",
        (SlotSpec(name="ratio", schema={"type": "number", "maximum": 1.0}),),
        {"ratio": 1.5})
    add("enum_violation",
        (SlotSpec(name="method", schema={"type": "string",
                                         "enum": ["idw", "kriging"]}),),
        {"method": "poly"})
    add("array_min_items",
        (SlotSpec(name="samples",
                  schema={"type": "array", "minItems": 2,
                          "items": {"type": "number"}}),),
        {"samples": [1.0]})
    add("items_type_error",
        (SlotSpec(name="samples",
                  schema={"type": "array", "items": {"type": "number"}}),),
        {"samples": [1.0, "oops"]})
    add("additional_properties_false",
        (SlotSpec(name="roi", schema={"type": "object",
                                      "additionalProperties": False}),),
        {"roi": {"extra": 1}})
    add("nested_required_missing",
        (SlotSpec(name="roi", schema={"type": "object", "required": ["il0"]}),),
        {"roi": {}})
    add("union_string_null_ok",
        (SlotSpec(name="v", schema={"type": ["string", "null"]}),),
        {"v": None})
    add("union_rejects_integer",
        (SlotSpec(name="v", schema={"type": ["string", "null"]}),),
        {"v": 3})
    add("unknown_schema_type",
        (SlotSpec(name="v", schema={"type": "float128"}),),
        {"v": 1.0})
    add("unknown_schema_type_non_string",
        (SlotSpec(name="v", schema={"type": 5}),),
        {"v": 1.0})
    add("union_all_unknown_types",
        (SlotSpec(name="v", schema={"type": ["float128"]}),),
        {"v": 1.0})
    add("enum_numeric_bool_pass",
        (SlotSpec(name="v", schema={"type": "integer", "enum": [1]}),),
        {"v": True})
    add("min_items_float",
        (SlotSpec(name="samples",
                  schema={"type": "array", "minItems": 2.0}),),
        {"samples": [1.0]})
    add("null_property_schema_additional_false",
        (SlotSpec(name="roi", schema={"type": "object",
                                      "properties": {"inner": None},
                                      "additionalProperties": False}),),
        {"roi": {"inner": {"a": 1}}})
    add("top_level_expected_object",
        (SlotSpec(name="roi", schema={"type": "object"}),),
        {"roi": "not-a-dict"})
    add("array_max_items",
        (SlotSpec(name="samples",
                  schema={"type": "array", "maxItems": 1}),),
        {"samples": [1.0, 2.0]})
    add("boolean_for_integer",
        (SlotSpec(name="n", schema={"type": "integer"}),),
        {"n": True})
    add("number_accepts_integer",
        (SlotSpec(name="n", schema={"type": "number"}),),
        {"n": 3})
    add("defaults_materialized_and_overridden",
        (SlotSpec(name="factor"),
         SlotSpec(name="grid_n", schema={"type": "integer"}, default=16),
         SlotSpec(name="opt", required=False, default=None)),
        {"factor": "RT", "grid_n": 64})
    add("default_used_when_absent",
        (SlotSpec(name="grid_n", schema={"type": "integer"}, default=16),),
        {})
    return cases


def _ShimRun(slot_values, context):
    return SimpleNamespace(slot_values=slot_values, context=context)


_CONTEXT = SimpleNamespace(
    workspace_id="测试工区",
    project_path="/tmp/demo.paleo.json",
    active_survey_id="S1",
    active_well_id="W1",
    current_map_id=None,
    selection=SimpleNamespace(
        active_well_id="W1",
        selected_well_ids=("W1", "W2"),
        seismic_cursor=None,
        depth_range=(100.0, 2000.5),
    ),
)

_CONTEXT_MAP = {
    "workspace_id": "测试工区",
    "project_path": "/tmp/demo.paleo.json",
    "active_survey_id": "S1",
    "active_well_id": "W1",
    "current_map_id": None,
    "selection.active_well_id": "W1",
    "selection.selected_well_ids": ["W1", "W2"],
    "selection.seismic_cursor": None,
    "selection.depth_range": [100.0, 2000.5],
}


def resolve_cases() -> list[dict]:
    results = {
        "a": {"version_ids": ["ver-1"], "n": 5, "k": None},
        "scalar_node": "not-a-dict",
    }
    cases: list[dict] = []

    def add(name, value, *, slot_values=None, run=None):
        run = run or _ShimRun(slot_values or {}, _CONTEXT)
        try:
            resolved = resolve_value(value, run=run, results=results)
            entry = {"name": name, "value": value,
                     "slot_values": run.slot_values,
                     "results": results,
                     "context": _CONTEXT_MAP,
                     "resolved": resolved, "error": None}
        except BindingError as exc:
            entry = {"name": name, "value": value,
                     "slot_values": run.slot_values,
                     "results": results,
                     "context": _CONTEXT_MAP,
                     "resolved": None, "error": str(exc)}
        cases.append(entry)

    add("slot_hit", {"$slot": "factor"}, slot_values={"factor": "GR"})
    add("slot_miss", {"$slot": "nope"}, slot_values={})
    add("ref_whole_outputs", {"$ref": "a"})
    add("ref_key_hit", {"$ref": "a", "key": "n"})
    add("ref_key_null_value_is_a_value", {"$ref": "a", "key": "k"})
    add("ref_key_missing", {"$ref": "a", "key": "m"})
    add("ref_unresolved", {"$ref": "ghost"})
    add("ref_outputs_not_dict", {"$ref": "scalar_node", "key": "n"})
    add("ref_key_non_string", {"$ref": "a", "key": 3})
    add("context_hit", {"$context": "workspace_id"})
    add("context_dotted_selection", {"$context": "selection.selected_well_ids"})

    def add_ctx(name, value, context, context_map):
        run = _ShimRun({}, context)
        try:
            resolved = resolve_value(value, run=run, results=results)
            entry = {"name": name, "value": value, "slot_values": {},
                     "results": results, "context": context_map,
                     "resolved": resolved, "error": None}
        except BindingError as exc:
            entry = {"name": name, "value": value, "slot_values": {},
                     "results": results, "context": context_map,
                     "resolved": None, "error": str(exc)}
        cases.append(entry)

    add_ctx("context_null_attr_is_unavailable", {"$context": "current_map_id"},
            _CONTEXT, _CONTEXT_MAP)
    partial = SimpleNamespace(workspace_id="W")
    add_ctx("context_attr_absent_is_unavailable", {"$context": "active_well_id"},
            partial, {"workspace_id": "W"})

    add("nested_dict_and_list_recursion",
        {"outer": {"$slot": "factor"}, "list": [{"$ref": "a"}, 1, None],
         "deep": {"k": [{"$ref": "a", "key": "n"}]}},
        slot_values={"factor": "RT"})
    add("scalars_passthrough", {"i": 42, "s": "x", "b": True, "n": None,
                                "f": 1.5})
    add("top_level_scalar", 7)
    add("top_level_list", [{"$slot": "factor"}, {"$ref": "a"}],
        slot_values={"factor": "GR"})

    # bind_parameters over a real NodeSpec
    spec = spec_of(nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",), parameters={
            "factor": {"$slot": "factor"},
            "up": {"$ref": "a", "key": "n"},
        }),
    ))
    bound = bind_parameters(spec.nodes[1], run=_ShimRun({"factor": "GR"}, _CONTEXT),
                            results=results)
    cases.append({
        "name": "bind_parameters_node",
        "value": spec.nodes[1].parameters,
        "slot_values": {"factor": "GR"},
        "results": results,
        "context": _CONTEXT_MAP,
        "resolved": bound,
        "error": None,
    })
    return cases


def canonical_hash_cases() -> list[dict]:
    value_sets = [
        ("simple", {"a": 1, "b": [1, 2, 3]}),
        ("order_independent_a", {"a": 1, "z": 2, "m": {"y": 1, "x": 2}}),
        ("order_independent_b", {"z": 2, "m": {"x": 2, "y": 1}, "a": 1}),
        ("chinese_keys", {"名称": "单因素图", "节点": [{"编号": 1}]}),
        ("int_vs_float_int", {"v": 1}),
        ("int_vs_float_float", {"v": 1.0}),
        ("bool_null_string", {"t": True, "n": None, "s": "a\"b'c\n"}),
        ("empty_objects", {"o": {}, "l": []}),
        ("nested_sorting", {"b": {"d": 1, "c": {"f": 2, "e": 1}}, "a": 3}),
    ]
    return [{
        "name": name,
        "value": value,
        "hash": dag_model.canonical_hash(value),
    } for name, value in value_sets]


def from_dict_error_cases() -> list[dict]:
    """Malformed inputs where Python RAISES (KeyError/ValueError/TypeError);
    the C++ test asserts that the port throws too (message text is not
    frozen — D5 documents the exception-type mapping). The python_error
    field is human-readable metadata; no test consumes it."""
    spec = spec_of(nodes=(node("a", "a.compute"),))
    bad = {
        "missing_node_id": {
            "workflow_id": "wf.bad", "name": "bad",
            "nodes": [{"action_id": "a.compute"}],
        },
        "null_nodes": {"workflow_id": "wf.bad", "name": "bad",
                       "nodes": None},
        "missing_workflow_id": {"name": "bad", "nodes": []},
    }
    cases = []
    for name, raw in bad.items():
        error = None
        try:
            WorkflowSpec.from_dict(raw)
        except Exception as exc:
            error = type(exc).__name__
        assert error is not None, name
        cases.append({"name": name, "spec": raw, "python_error": error})
    # NodeRun state + WorkflowRun state: unknown strings are ValueError.
    run_raw = {"run_id": "x", "workflow": spec.to_dict(), "state": "bogus"}
    error = None
    try:
        WorkflowRun.from_dict(run_raw)
    except Exception as exc:
        error = type(exc).__name__
    assert error == "ValueError", error
    cases.append({"name": "unknown_run_state", "spec": run_raw,
                  "python_error": error})

    node_run_raw = {"node_id": "a", "state": "bogus"}
    error = None
    try:
        NodeRun.from_dict(node_run_raw)
    except Exception as exc:
        error = type(exc).__name__
    assert error == "ValueError", error
    cases.append({"name": "unknown_node_run_state",
                  "spec": node_run_raw, "python_error": error})
    return cases


def run_roundtrip_cases() -> list[dict]:
    spec = spec_of(workflow_id="wf.runrt", name="runrt", nodes=(
        node("a", "a.compute"),
        node("b", "b.compute", depends_on=("a",)),
    ))
    run = WorkflowRun.create(spec, {"factor": "GR"})
    run.run_id = "fullrun00000001"  # overwrite the random id: frozen fixture
    run.state = RunState.COMPLETED
    run.project_name = "工程甲"
    run.project_path = "/tmp/demo.paleo.json"
    run.parent_run_id = "orig0001"
    run.created_at = 1758144000.0
    run.updated_at = 1758144060.5
    nr_a = run.node_runs["a"]
    nr_a.state = NodeState.SUCCEEDED
    nr_a.attempt = 1
    nr_a.action_status = "success"
    nr_a.from_cache = False
    nr_a.parameters = {"factor": "GR"}
    nr_a.input_version_ids = ("ver-in-1",)
    nr_a.cache_identity = "identity-a"
    nr_a.output_version_ids = ("ver-out-1",)
    nr_a.outputs = {"version_ids": ["ver-out-1"]}
    nr_a.receipt = {"status": "success", "action_id": "a.compute"}
    nr_a.started_at = 1758144001.0
    nr_a.finished_at = 1758144002.0
    run.node_runs["b"].state = NodeState.SKIPPED
    run.node_runs["b"].skip_reason = "条件未满足"

    reserialized = WorkflowRun.from_dict(run.to_dict()).to_dict()
    assert reserialized == run.to_dict()
    full = {
        "name": "full_run_fields",
        "run": run.to_dict(),
        "reserialized": reserialized,
    }

    # Store schema drift as it reaches from_dict on disk: the checkpoint
    # file is missing node b's entry; from_dict setdefaults it to PENDING.
    drifted_input = run.to_dict()
    drifted_input["node_runs"] = [
        entry for entry in drifted_input["node_runs"]
        if entry["node_id"] != "b"
    ]
    drifted_expected = WorkflowRun.from_dict(drifted_input).to_dict()

    minimal_raw = {
        "run_id": "abc123",
        "workflow": spec.to_dict(),
    }
    minimal = WorkflowRun.from_dict(minimal_raw)

    # Every NodeState / RunState value round-trips.
    all_states = WorkflowRun.create(spec, {})
    all_states.run_id = "states0000000001"
    all_states.created_at = 1758144000.0  # overwrite wall clock: frozen
    all_states.updated_at = 1758144000.0
    all_states.state = RunState.INTERRUPTED
    ordered_states = [
        NodeState.PENDING, NodeState.RUNNING, NodeState.SUCCEEDED,
        NodeState.FAILED, NodeState.CANCELLED, NodeState.SKIPPED,
        NodeState.UNAVAILABLE,
    ]
    all_states.node_runs["a"].state = ordered_states[0]
    all_states.node_runs["b"].state = ordered_states[6]
    extra_states = dict(zip(
        ["c", "d", "e", "f", "g"],
        [ordered_states[i] for i in (1, 2, 3, 4, 5)],
    ))
    for node_id, state in extra_states.items():
        run_node = NodeRun(node_id=node_id, state=state)
        all_states.node_runs[node_id] = run_node
    all_states_reserialized = WorkflowRun.from_dict(
        all_states.to_dict()).to_dict()
    assert all_states_reserialized == all_states.to_dict()

    return [
        {
            "name": "all_enum_states",
            "run": all_states.to_dict(),
            "reserialized": all_states_reserialized,
        },
        full,
        {
            "name": "store_drift_setdefault",
            "run": drifted_input,
            "reserialized": drifted_expected,
        },
        {
            "name": "minimal_defaults",
            "run": minimal_raw,
            "reserialized": minimal.to_dict(),
        },
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fixture = {
        "kind": "workflow_spec_oracle",
        "generator": "tools/oracle/generate_workflow_spec_fixtures.py",
        "python": {
            "workflow_schema_version": dag_model.WORKFLOW_SCHEMA_VERSION,
            "condition_kinds_sorted": sorted(dag_model._CONDITION_KINDS),
            "context_whitelist_sorted": sorted(dag_validation.CONTEXT_BINDING_WHITELIST),
            "node_id_pattern": r"^[a-z][a-z0-9_]*$",
            "workflow_id_pattern": r"^[a-z][a-z0-9_.-]{1,63}$",
        },
        "valid_specs": valid_spec_cases(),
        "invalid_specs": invalid_spec_cases(),
        "condition_trees": condition_tree_cases(),
        "slot_bindings": slot_binding_cases(),
        "resolve": resolve_cases(),
        "canonical_hash": canonical_hash_cases(),
        "run_roundtrip": run_roundtrip_cases(),
        "from_dict_error": from_dict_error_cases(),
    }
    out_path = OUT / "workflow_spec_oracle.json"
    out_path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = {k: len(v) for k, v in fixture.items()
              if isinstance(v, list)}
    print(f"frozen {out_path}")
    for key, n in counts.items():
        print(f"  {key}: {n}")
    assert counts["valid_specs"] >= 20, counts
    assert counts["invalid_specs"] >= 20, counts


if __name__ == "__main__":
    main()
