#!/usr/bin/env python3
"""Oracle fixture generator for the C++ workflow recipe port (CONV-33,
libs/workflow_engine recipe.cpp).

Imports the REAL implementations (paleo_workbench.workflow.recipe +
workflow.dag.model / validation) and freezes their observable behaviour to
JSON so the C++ port can be verified against the Python chain. Regenerate
with:

    QT_QPA_PLATFORM=offscreen python tools/oracle/generate_workflow_recipe_fixtures.py

Frozen surfaces (13 case families): save/load round-trip with the EXACT
checkpoint FILE BYTES (indent=1, ensure_ascii=False, no trailing newline)
plus nested-parent mkdir; the forbidden-key / absolute-path structural
gates (verbatim messages incl. Python repr quoting and the em-dash); the
.load JSON-parse error messages (CPython json.JSONDecodeError detail,
including the 3.13+ "Illegal trailing comma" wording); migrate_recipe v1
identity + nested schema_version injection + fail-closed unknown version;
the .json -> .paleo-workflow.json suffix rewrite; clone identity;
diff_recipes (nodes/slots/max_concurrency); inspect shape; recipe_from_run
slot-default promotion; recipe_from_spec slug ids; from_dict coercions; and
the save/load refusal gates ("; "-joined problems, registry validation,
missing file).

Determinism: every time.time() site runs under a patched fixed clock; all
workflow/run ids are fixed strings.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.harness.registry import (  # noqa: E402
    ActionRegistry,
    ActionRisk,
    ActionSpec,
)
from paleo_workbench.workflow.dag.model import (  # noqa: E402
    WorkflowRun,
    WorkflowSpec,
    canonical_hash,
)
from paleo_workbench.workflow.dag.validation import validate_workflow_spec  # noqa: E402
from paleo_workbench.workflow.recipe import (  # noqa: E402
    RECIPE_SCHEMA_VERSION,
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
    structural_problems,
    validate_recipe,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_engine"
    / "workflow_engine_tests"
    / "fixtures"
    / "workflow_recipe_oracle.json"
)

# The spec is frozen as a plain dict; BOTH sides build it through
# WorkflowSpec.from_dict(same dict) so the parsed spec (and spec_hash) is
# identical by construction.
SPEC_DICT = {
    "workflow_id": "wf-recipe-parity",
    "name": "Recipe Parity Spec",
    "description": "CONV-33 recipe oracle spec",
    "max_concurrency": 2,
    "schema_version": "1.0",
    "slots": [
        {
            "name": "horizon",
            "schema": {"type": "string"},
            "required": True,
            "default": "H1",
            "description": "target horizon",
        },
        {
            "name": "grid_n",
            "schema": {"type": "integer", "minimum": 4},
            "required": False,
            "default": 8,
            "description": "",
        },
    ],
    "nodes": [
        {
            "node_id": "extract",
            "action_id": "map.extract_factors",
            "parameters": {
                "factor_name": "gr",
                "target_horizon": "$slot:horizon",
                "nested": {"k": [1, 2.5, "ü"]},
            },
            "depends_on": [],
            "condition": None,
            "retry": {"max_attempts": 2, "backoff_seconds": 0.5},
            "description": "extract points",
        },
        {
            "node_id": "interp",
            "action_id": "map.interpolate_idw",
            "parameters": {
                "samples": {"$ref": "extract", "key": "points"},
                "grid_n": "$slot:grid_n",
            },
            "depends_on": ["extract"],
            "condition": {"kind": "node_succeeded", "node": "extract"},
            "retry": {"max_attempts": 1, "backoff_seconds": 0.0},
            "description": "",
        },
    ],
}

RUN_SPEC_DICT = {
    "workflow_id": "wf.from-run",
    "name": "From-Run Spec",
    "description": "slot promotion spec",
    "max_concurrency": 3,
    "schema_version": "1.0",
    "slots": [
        {
            "name": "horizon",
            "schema": {"type": "string"},
            "required": True,
            "default": "H1",
            "description": "target horizon",
        },
        {
            "name": "grid_n",
            "schema": {"type": "integer", "minimum": 4},
            "required": False,
            "default": 8,
            "description": "",
        },
        {
            "name": "note",
            "schema": {"type": "string"},
            "required": False,
            "default": None,
            "description": "free note",
        },
    ],
    "nodes": [
        {
            "node_id": "extract",
            "action_id": "map.extract_factors",
            "parameters": {"factor_name": "gr"},
            "depends_on": [],
            "condition": None,
            "retry": {"max_attempts": 1, "backoff_seconds": 0.0},
            "description": "",
        },
    ],
}

FIXED_CLOCK = 1712345678.5
SECOND_CLOCK = 1712345699.25


# --------------------------------------------------------------- clocks --
class FixedClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class patched_time:
    """Point recipe.py's `time.time` (and everything else using the time
    module) at a deterministic fake; restored on exit."""

    def __init__(self, clock) -> None:
        self.clock = clock

    def __enter__(self):
        import time

        self._orig = time.time
        time.time = self.clock
        return self

    def __exit__(self, *exc):
        import time

        time.time = self._orig
        return False


def build_registry() -> ActionRegistry:
    reg = ActionRegistry()
    for name in ("map.extract_factors", "map.interpolate_idw", "test.noop"):
        reg.register(ActionSpec(
            action_id=name,
            description=f"{name} oracle action",
            handler=lambda ctx, p: {},
            risk=ActionRisk.COMPUTE,
        ))
    return reg


def main() -> None:
    spec = WorkflowSpec.from_dict(SPEC_DICT)
    run_spec = WorkflowSpec.from_dict(RUN_SPEC_DICT)
    reg = build_registry()
    doc = {
        "python": {
            "generator": "tools/oracle/generate_workflow_recipe_fixtures.py",
            "modules": [
                "paleo_workbench.workflow.recipe",
                "paleo_workbench.workflow.dag.model",
                "paleo_workbench.workflow.dag.validation",
            ],
            "recipe_schema_version": RECIPE_SCHEMA_VERSION,
        },
        "spec": SPEC_DICT,
        "spec_hash": spec.spec_hash,
        "run_spec": RUN_SPEC_DICT,
        "run_spec_hash": run_spec.spec_hash,
        "registry": {
            s.action_id: s.risk.value for s in reg.specs()
        },
        "fixed_clock": FIXED_CLOCK,
        "second_clock": SECOND_CLOCK,
    }

    # ---------------------------------------- 1. save/load round-trip --
    root = Path(tempfile.mkdtemp(prefix="pwb-recipe-c01-"))
    with patched_time(FixedClock(FIXED_CLOCK)):
        recipe = recipe_from_spec(
            spec, description="round-trip recipe", tags=("demo", "parity")
        )
    assert recipe.created_at == FIXED_CLOCK
    path = save_recipe(recipe, root / "wf-recipe-parity.json")
    text = path.read_text(encoding="utf-8")
    assert not text.endswith("\n"), "recipe file must have NO trailing newline"
    loaded = load_recipe(path)
    assert loaded.to_dict() == recipe.to_dict()
    doc["case01_roundtrip"] = {
        "filename": path.name,
        "recipe_to_dict": recipe.to_dict(),
        "bytes": text,
        "bytes_sha": _sha(text),
        "loaded_to_dict": loaded.to_dict(),
        "loaded_hash": canonical_hash(loaded.to_dict()),
        # save into a NOT-yet-existing nested parent (mkdir parents=True)
        "nested_rel": "sub/dir/nested.paleo-workflow.json",
        "nested_bytes": save_recipe(recipe, root / "sub" / "dir" /
                                    "nested.paleo-workflow.json")
        .read_text(encoding="utf-8"),
        "nested_created": (root / "sub" / "dir").is_dir(),
    }

    # ------------------------------------------- 2. forbidden keys gate --
    forbidden_cases = [
        # api_key with a STRING value -> flagged, lowered key in message
        {"workflow": {"parameters": {"api_key": "k-123"}}},
        # forbidden key with a NON-string value recurses normally; the
        # nested "token" string is then flagged under the sql path
        {"sql": {"query_x": 1, "token": "t"}},
        # key case/whitespace normalization: " ApiKey " -> apikey
        {"nodes": [{"parameters": {" ApiKey ": "v"}}]},
        # sql + code keys, list indexing into the path
        {"a": [0, {"Code": "print(1)"}]},
        # non-forbidden look-alikes pass
        {"tokens_total": 3, "source_dir": "data", "pass": 1},
        # dict-typed forbidden key whose subtree is clean -> no problems
        {"secret": {"public": "ok"}},
        # top-level tags list path indexing
        {"tags": ["ok", {"password": "p"}]},
    ]
    doc["case02_forbidden_keys"] = [
        {"data": case, "problems": structural_problems(case)}
        for case in forbidden_cases
    ]
    # validate_recipe = structural + workflow validation (registry surface)
    with patched_time(FixedClock(FIXED_CLOCK)):
        bad_action_recipe = recipe_from_spec(
            WorkflowSpec.from_dict({
                **SPEC_DICT,
                "workflow_id": "wf-recipe-parity",
                "nodes": [
                    {**SPEC_DICT["nodes"][0], "action_id": "no.such.action"},
                ],
            }),
        )
    doc["case02_validate_recipe"] = {
        "recipe_workflow_id": bad_action_recipe.workflow.workflow_id,
        "problems": validate_recipe(bad_action_recipe, reg),
    }

    # ------------------------------------------ 3. absolute path gate --
    path_cases = [
        {"out": "/etc/passwd"},                    # posix
        {"out": "\\\\server\\share\\data"},        # UNC (two leading backslashes)
        {"out": "C:\\data\\wells"},                # windows drive, backslash
        {"out": "D:/abs/path"},                    # windows drive, forward
        {"out": "$/mnt/seismic"},                  # $-exempt
        {"out": "$C:\\kept"},                      # $-exempt (checked on raw)
        {"out": "data/out.json"},                  # relative -> fine
        {"out": " /leading-space"},                # stripped match, raw repr
        {"out": "\\single"},                       # ONE backslash: no match
        {"parameters": {"path": "/abs"}},          # nested
        {"list": ["/abs", "ok"]},                  # list indexing
    ]
    doc["case03_absolute_paths"] = [
        {"data": case, "problems": structural_problems(case)}
        for case in path_cases
    ]

    # ----------------------------------------------- 4. corrupt JSON load --
    corrupt_corpus = {
        "broken1.paleo-workflow.json": "{corrupted",
        "broken2.paleo-workflow.json": '{"recipe_id": "x",}',
        "broken3.paleo-workflow.json": '{"a":1',
        "broken4.paleo-workflow.json": "{} trailing",
        "broken5.paleo-workflow.json": '{\n "recipe_id": "x",\n "tags": [1 2]\n}',
        "broken6.paleo-workflow.json": '{"recipe_id": "unc',
        "broken7.paleo-workflow.json": "corrupted{}",
        "broken8.paleo-workflow.json": "",
    }
    corrupt_root = Path(tempfile.mkdtemp(prefix="pwb-recipe-c04-"))
    corrupt_cases = []
    for name, raw in corrupt_corpus.items():
        (corrupt_root / name).write_text(raw, encoding="utf-8")
        try:
            load_recipe(corrupt_root / name)
            raise AssertionError(f"{name} must raise")
        except RecipeError as exc:
            message = str(exc)
        assert message.startswith(f"recipe {name!r} is not valid JSON: "), message
        corrupt_cases.append({"filename": name, "raw": raw, "message": message})
    doc["case04_corrupt_json"] = corrupt_cases

    # --------------------------------------------------- 5. migrate --
    migrate_cases = [
        # v1 identity: nothing injected when both keys exist
        {"recipe_schema_version": "1.0", "workflow": {"schema_version": "9.9"}},
        # workflow missing -> injected at END of key order
        {"recipe_schema_version": "1.0", "recipe_id": "r", "name": "n"},
        # workflow present without schema_version -> injected at END
        {"recipe_schema_version": "1.0", "workflow": {"workflow_id": "w"}},
        # version key missing -> defaults to 1.0 (identity + injection)
        {"recipe_id": "r"},
    ]
    doc["case05_migrate"] = [
        {"data": case, "migrated": migrate_recipe(dict(case))}
        for case in migrate_cases
    ]
    migrate_refusals = [
        {"recipe_schema_version": "1.1"},
        {"recipe_schema_version": 2.0},   # float -> str -> "2.0"
        {"recipe_schema_version": None},  # None -> str -> "None"
    ]
    refusal_cases = []
    for case in migrate_refusals:
        try:
            migrate_recipe(dict(case))
            raise AssertionError("unknown version must raise")
        except RecipeError as exc:
            refusal_cases.append({"data": case, "message": str(exc)})
    doc["case05_migrate_refusals"] = refusal_cases

    # -------------------------------------------- 6. suffix rewrite --
    root = Path(tempfile.mkdtemp(prefix="pwb-recipe-c06-"))
    with patched_time(FixedClock(FIXED_CLOCK)):
        recipe = recipe_from_spec(spec, recipe_id="suffix-demo")
    suffix_cases = []
    for given, expected in (
        ("plain.json", "plain.paleo-workflow.json"),
        ("dot.name.json", "dot.name.paleo-workflow.json"),
        ("already.paleo-workflow.json", "already.paleo-workflow.json"),
        ("notes.txt", "notes.txt"),
        ("noext", "noext"),
    ):
        with patched_time(FixedClock(FIXED_CLOCK)):
            out = save_recipe(recipe, root / given)
        suffix_cases.append({
            "given": given,
            "returned": out.name,
            "expected": expected,
            "exists": out.exists(),
        })
    doc["case06_suffix_rewrite"] = suffix_cases

    # ---------------------------------------------------- 7. clone --
    with patched_time(FixedClock(FIXED_CLOCK)):
        original = recipe_from_spec(
            spec, description="clone me", tags=("t1",)
        )
        original.source_run_id = "run-abcd1234ef567890"
    with patched_time(FixedClock(SECOND_CLOCK)):
        default_clone = clone_recipe(original)
        named_clone = clone_recipe(original, new_recipe_id="custom-id")
        renamed_clone = clone_recipe(original, new_recipe_id="")
    doc["case07_clone"] = {
        "original_to_dict": original.to_dict(),
        "default": default_clone.to_dict(),
        "named": named_clone.to_dict(),
        # empty-string id is falsy in Python `or` -> default -clone id
        "empty_id_falls_back": renamed_clone.recipe_id,
        "independent_workflow": default_clone.workflow is not original.workflow,
    }
    # clone of a recipe whose name is "" -> from_dict re-coerces
    # name = workflow.name
    with patched_time(FixedClock(FIXED_CLOCK)):
        empty_named = recipe_from_spec(spec, recipe_id="empty-name")
    empty_named.name = ""
    with patched_time(FixedClock(SECOND_CLOCK)):
        clone_empty_named = clone_recipe(empty_named)
    doc["case07_clone_empty_name"] = {
        "cloned_name": clone_empty_named.name,
        "to_dict": clone_empty_named.to_dict(),
    }

    # ---------------------------------------------------- 8. diff --
    with patched_time(FixedClock(FIXED_CLOCK)):
        base = recipe_from_spec(spec)
    changed_spec = WorkflowSpec.from_dict({
        **SPEC_DICT,
        "max_concurrency": 4,
        "slots": [
            SPEC_DICT["slots"][0],
            {**SPEC_DICT["slots"][1], "default": 16, "required": True},
            {
                "name": "extra",
                "schema": {"type": "string"},
                "required": False,
                "default": None,
                "description": "added slot",
            },
        ],
        "nodes": [
            SPEC_DICT["nodes"][0],
            {
                **SPEC_DICT["nodes"][1],
                "description": "changed interp",
                "retry": {"max_attempts": 3, "backoff_seconds": 0.5},
            },
            {
                "node_id": "report",
                "action_id": "test.noop",
                "parameters": {},
                "depends_on": ["extract", "interp"],
                "condition": None,
                "retry": {"max_attempts": 1, "backoff_seconds": 0.0},
                "description": "",
            },
        ],
    })
    with patched_time(FixedClock(FIXED_CLOCK)):
        other = recipe_from_spec(changed_spec, recipe_id="wf-recipe-parity")
    # slot removed variant
    removed_slot_spec = WorkflowSpec.from_dict({
        **SPEC_DICT,
        "slots": [SPEC_DICT["slots"][0]],
    })
    with patched_time(FixedClock(FIXED_CLOCK)):
        removed = recipe_from_spec(removed_slot_spec, recipe_id="wf-recipe-parity")
    with patched_time(FixedClock(FIXED_CLOCK)):
        self_diff = recipe_from_spec(spec, recipe_id="wf-recipe-parity")
    doc["case08_diff"] = {
        "changed": diff_recipes(base, other),
        "slot_removed": diff_recipes(base, removed),
        "reverse_changed": diff_recipes(other, base),
        "empty": diff_recipes(base, self_diff),
    }

    # -------------------------------------------------- 9. inspect --
    with patched_time(FixedClock(FIXED_CLOCK)):
        recipe = recipe_from_spec(
            spec, description="inspect me", tags=("a", "b")
        )
        recipe.source_run_id = "run-1234567890abcdef"
    doc["case09_inspect"] = inspect_recipe(recipe)

    # ------------------------------------------- 10. recipe_from_run --
    run = WorkflowRun.create(run_spec, {"horizon": "H9", "unknown_slot": 42})
    run.run_id = "run-ff00ff00ff00ff00"
    with patched_time(FixedClock(FIXED_CLOCK)):
        from_run = recipe_from_run(run, tags=("from-run",))
    doc["case10_from_run"] = {
        "run_id": run.run_id,
        "slot_values": run.slot_values,
        "recipe_to_dict": from_run.to_dict(),
        "slots": [s.to_dict() for s in from_run.workflow.slots],
    }

    # ------------------------------------------- 11. recipe_from_spec --
    with patched_time(FixedClock(FIXED_CLOCK)):
        default_id = recipe_from_spec(spec)
        custom_id = recipe_from_spec(spec, recipe_id="Custom ID!!")
        empty_id = recipe_from_spec(spec, recipe_id="")
        with_desc = recipe_from_spec(
            spec, description="explicit", tags=("x",)
        )
    unicode_spec = WorkflowSpec.from_dict({
        **RUN_SPEC_DICT,
        "workflow_id": "WF.Ünicode 2024",
        "description": "fallback description",
    })
    with patched_time(FixedClock(FIXED_CLOCK)):
        unicode_recipe = recipe_from_spec(unicode_spec)
    doc["case11_from_spec"] = {
        "default_id": default_id.recipe_id,
        "default_created_at": default_id.created_at,
        "custom_id": custom_id.recipe_id,
        "empty_id_falls_back": empty_id.recipe_id,
        "desc_fallback": default_id.description,   # "" -> workflow.description
        "explicit_desc": with_desc.description,
        "unicode_slug": unicode_recipe.recipe_id,
        "unicode_desc_fallback": unicode_recipe.description,
        "tags": list(with_desc.tags),
        "workflow_carried": default_id.workflow.to_dict() == spec.to_dict(),
    }

    # ---------------------------------------------- 12. refusal gates --
    root = Path(tempfile.mkdtemp(prefix="pwb-recipe-c12-"))
    gate_cases = {}
    # (a) structural refusal at save (joined with "; "), nothing written.
    # NOTE: deepcopy — recipe_from_spec stores the workflow by REFERENCE in
    # Python, so mutating smuggler's parameters would otherwise leak into
    # every earlier-frozen dict that aliases spec's node parameters.
    with patched_time(FixedClock(FIXED_CLOCK)):
        smuggler = recipe_from_spec(copy.deepcopy(spec), recipe_id="smuggler")
    smuggler.workflow.nodes[0].parameters["api_key"] = "k"
    smuggler.workflow.nodes[1].parameters["output_path"] = "/etc/passwd"
    try:
        save_recipe(smuggler, root / "smuggler.paleo-workflow.json")
        raise AssertionError("smuggler save must raise")
    except RecipeError as exc:
        gate_cases["save_structural_message"] = str(exc)
    gate_cases["save_structural_wrote_nothing"] = not (
        root / "smuggler.paleo-workflow.json"
    ).exists() and not any(root.iterdir())
    # (b) registry validation refusal at save
    with patched_time(FixedClock(FIXED_CLOCK)):
        unknown_action = recipe_from_spec(
            WorkflowSpec.from_dict({
                **SPEC_DICT,
                "nodes": [
                    {**SPEC_DICT["nodes"][0], "action_id": "no.such.action"},
                ],
            }),
            recipe_id="unknown-action",
        )
    try:
        save_recipe(unknown_action, root / "unknown.paleo-workflow.json",
                    registry=reg)
        raise AssertionError("unknown-action save must raise")
    except RecipeError as exc:
        gate_cases["save_registry_message"] = str(exc)
    gate_cases["save_registry_wrote_nothing"] = not any(root.iterdir())
    # same recipe saved WITHOUT a registry -> allowed (registry=None skips)
    with patched_time(FixedClock(FIXED_CLOCK)):
        out = save_recipe(unknown_action, root / "unknown.paleo-workflow.json")
    gate_cases["save_no_registry_ok"] = out.exists()
    gate_cases["save_no_registry_validates"] = (
        validate_workflow_spec(unknown_action.workflow, reg)
        == validate_recipe(unknown_action, reg)
    )
    # (c) load missing file
    try:
        load_recipe(root / "ghost.paleo-workflow.json")
        raise AssertionError("missing load must raise")
    except RecipeError as exc:
        gate_cases["load_missing_message"] = str(exc)
    # (d) structural refusal at load
    payload = {
        "recipe_schema_version": "1.0",
        "recipe_id": "evil",
        "name": "Evil",
        "description": "",
        "created_at": None,
        "source_run_id": None,
        "tags": [],
        "workflow": {
            "schema_version": "1.0",
            "workflow_id": "wf-evil",
            "name": "Evil",
            "description": "",
            "max_concurrency": 1,
            "slots": [],
            "nodes": [
                {
                    "node_id": "n1",
                    "action_id": "test.noop",
                    "parameters": {"token": "t"},
                    "depends_on": [],
                    "condition": None,
                    "retry": {"max_attempts": 1, "backoff_seconds": 0.0},
                    "description": "",
                }
            ],
        },
    }
    (root / "evil.paleo-workflow.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    try:
        load_recipe(root / "evil.paleo-workflow.json")
        raise AssertionError("evil load must raise")
    except RecipeError as exc:
        gate_cases["load_structural_message"] = str(exc)
    doc["case12_refusal_gates"] = gate_cases

    # -------------------------------------------- 13. from_dict coercions --
    with patched_time(FixedClock(FIXED_CLOCK)):
        recipe = recipe_from_spec(spec, recipe_id="coerce", tags=("t",))
        recipe.source_run_id = "run-coerce00000000"
    d = json.loads(json.dumps(recipe.to_dict(), ensure_ascii=False))
    del d["name"]           # -> workflow.name fallback
    del d["description"]    # -> ""
    del d["tags"]           # -> ()
    del d["source_run_id"]  # -> None
    del d["created_at"]     # -> None
    del d["recipe_schema_version"]  # -> RECIPE_SCHEMA_VERSION
    del d["workflow"]["schema_version"]  # migrate injects
    coerced = RecipeDocument.from_dict(d)
    doc["case13_from_dict"] = {
        "input": d,
        "name_fallback": coerced.name,
        "description": coerced.description,
        "created_at": coerced.created_at,
        "source_run_id": coerced.source_run_id,
        "tags": list(coerced.tags),
        "schema_version": coerced.schema_version,
        "workflow_schema_version": coerced.workflow.schema_version,
        "to_dict": coerced.to_dict(),
    }

    target = OUT
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(
        f"wrote {target} ({target.stat().st_size} bytes, 13 oracle cases, "
        f"spec_hash {doc['spec_hash'][:12]}...)"
    )


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    main()
