"""Recipe format (H4): portable ``*.paleo-workflow.json`` documents.

A recipe is the serialised body of a :class:`WorkflowSpec` plus metadata.
It deliberately stores *no* execution facts (no secrets, no tokens, no
absolute write paths, no SQL, no code) — those live in the session, the
project and the catalog. Structural rules are enforced at save AND load:
a recipe that smuggles an API key, a query or a script is refused, never
silently carried.

Supported lifecycle: save (from a spec or a successful run) → load
(schema-migrated, structurally validated) → clone → rerun-with-new-inputs
(slot re-binding) → diff → inspect.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.workflow.dag.model import WORKFLOW_SCHEMA_VERSION, WorkflowSpec
from paleo_workbench.workflow.dag.validation import validate_workflow_spec

RECIPE_SCHEMA_VERSION = "1.0"
RECIPE_SUFFIX = ".paleo-workflow.json"

_FORBIDDEN_KEYS = {
    "api_key", "apikey", "token", "secret", "password", "passwd", "credential",
    "sql", "query", "statement", "code", "script", "source", "eval", "exec",
    "shell", "command",
}
_ABSOLUTE_PATH_RE = re.compile(r"^(/|\\\\|[A-Za-z]:[/\\])")


class RecipeError(ValueError):
    """Refusal to save/load a recipe that violates the format contract."""


@dataclass(slots=True)
class RecipeDocument:
    """A portable workflow recipe (metadata + the WorkflowSpec body)."""

    recipe_id: str
    name: str
    workflow: WorkflowSpec
    description: str = ""
    created_at: float | None = None
    source_run_id: str | None = None
    tags: tuple[str, ...] = ()
    schema_version: str = RECIPE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_schema_version": self.schema_version,
            "recipe_id": self.recipe_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "source_run_id": self.source_run_id,
            "tags": list(self.tags),
            "workflow": self.workflow.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecipeDocument":
        data = migrate_recipe(data)
        workflow = WorkflowSpec.from_dict(data["workflow"])
        return cls(
            recipe_id=str(data["recipe_id"]),
            name=str(data.get("name") or workflow.name),
            workflow=workflow,
            description=str(data.get("description") or ""),
            created_at=data.get("created_at"),
            source_run_id=data.get("source_run_id"),
            tags=tuple(data.get("tags") or ()),
            schema_version=str(data.get("recipe_schema_version", RECIPE_SCHEMA_VERSION)),
        )


# ------------------------------------------------------------ security gate --

def _check_forbidden(value: Any, *, path: str, problems: list[str]) -> None:
    if isinstance(value, dict):
        for key, sub in value.items():
            key_l = str(key).strip().lower()
            if key_l in _FORBIDDEN_KEYS and isinstance(sub, str):
                problems.append(f"{path}.{key}: forbidden recipe key ({key_l})")
            else:
                _check_forbidden(sub, path=f"{path}.{key}", problems=problems)
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            _check_forbidden(sub, path=f"{path}[{i}]", problems=problems)
    elif isinstance(value, str):
        if _ABSOLUTE_PATH_RE.match(value.strip()) and not value.startswith("$"):
            problems.append(
                f"{path}: absolute path {value!r} — recipes are portable; "
                "use workspace-relative paths or slot bindings"
            )


def structural_problems(data: dict[str, Any]) -> list[str]:
    """Format-contract violations (secrets/paths/SQL/code smuggling)."""
    problems: list[str] = []
    _check_forbidden(data, path="recipe", problems=problems)
    return problems


# ----------------------------------------------------------------- migrate --

def migrate_recipe(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate a recipe dict to the current schema version.

    v1 is the first version — identity. Later versions append explicit,
    tested steps here; loading an unknown future version is refused
    (fail-closed), never best-effort guessed.
    """
    version = str(data.get("recipe_schema_version", RECIPE_SCHEMA_VERSION))
    if version == "1.0":
        data.setdefault("workflow", {}).setdefault(
            "schema_version", WORKFLOW_SCHEMA_VERSION
        )
        return data
    raise RecipeError(
        f"recipe schema version {version!r} is newer than this build supports "
        f"({RECIPE_SCHEMA_VERSION}) — upgrade paleo-workbench"
    )


# -------------------------------------------------------------- save/load --

def validate_recipe(recipe: RecipeDocument, registry: Any) -> list[str]:
    problems = structural_problems(recipe.to_dict())
    problems.extend(validate_workflow_spec(recipe.workflow, registry))
    return problems


def save_recipe(
    recipe: RecipeDocument,
    path: str | Path,
    *,
    registry: Any | None = None,
) -> Path:
    """Atomically write ``<name>.paleo-workflow.json``.

    The structural security gate runs BEFORE anything is written: a recipe
    carrying secrets, absolute write paths, SQL or code is refused.
    """
    problems = structural_problems(recipe.to_dict())
    if problems:
        raise RecipeError("; ".join(problems))
    if registry is not None:
        problems = validate_workflow_spec(recipe.workflow, registry)
        if problems:
            raise RecipeError("; ".join(problems))
    path = Path(path)
    if path.suffix == ".json" and not path.name.endswith(RECIPE_SUFFIX):
        path = path.with_name(path.stem + RECIPE_SUFFIX)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = recipe.to_dict()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent or Path(".")), prefix=".tmp-recipe-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def load_recipe(path: str | Path) -> RecipeDocument:
    """Load + migrate + structurally validate one recipe file."""
    path = Path(path)
    if not path.exists():
        raise RecipeError(f"recipe file {path.name!r} does not exist")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecipeError(f"recipe {path.name!r} is not valid JSON: {exc}") from exc
    problems = structural_problems(data)
    if problems:
        raise RecipeError("; ".join(problems))
    return RecipeDocument.from_dict(data)


# ------------------------------------------------------- lifecycle helpers --

def recipe_from_spec(
    workflow: WorkflowSpec,
    *,
    recipe_id: str | None = None,
    description: str = "",
    tags: tuple[str, ...] = (),
) -> RecipeDocument:
    return RecipeDocument(
        recipe_id=recipe_id or _slug(workflow.workflow_id),
        name=workflow.name,
        workflow=workflow,
        description=description or workflow.description,
        created_at=time.time(),
        tags=tags,
    )


def recipe_from_run(run: Any, *, tags: tuple[str, ...] = ()) -> RecipeDocument:
    """Save-from-successful-run: slot values become defaults so the recipe
    re-runs with new inputs by overriding them."""
    workflow = run.workflow
    slots = []
    for slot in workflow.slots:
        overrides = {}
        if slot.name in run.slot_values:
            overrides["default"] = run.slot_values[slot.name]
        if overrides:
            from paleo_workbench.workflow.dag.model import SlotSpec

            slot = SlotSpec(
                name=slot.name,
                schema=slot.schema,
                required=slot.required,
                description=slot.description,
                **overrides,
            )
        slots.append(slot)
    migrated = WorkflowSpec(
        workflow_id=workflow.workflow_id,
        name=workflow.name,
        nodes=workflow.nodes,
        slots=tuple(slots),
        schema_version=workflow.schema_version,
        max_concurrency=workflow.max_concurrency,
        description=workflow.description,
    )
    return RecipeDocument(
        recipe_id=_slug(workflow.workflow_id),
        name=workflow.name,
        workflow=migrated,
        description=workflow.description,
        created_at=time.time(),
        source_run_id=run.run_id,
        tags=tags,
    )


def clone_recipe(recipe: RecipeDocument, *, new_recipe_id: str | None = None) -> RecipeDocument:
    """Deep copy under a fresh identity — a safe starting point for edits."""
    data = json.loads(json.dumps(recipe.to_dict(), ensure_ascii=False))
    data["recipe_id"] = new_recipe_id or f"{recipe.recipe_id}-clone"
    data["created_at"] = time.time()
    data["source_run_id"] = None
    return RecipeDocument.from_dict(data)


def diff_recipes(a: RecipeDocument, b: RecipeDocument) -> dict[str, Any]:
    """Structural diff (nodes/slots/params), for inspect/review workflows."""
    changes: dict[str, Any] = {}
    an = {n.node_id: n.to_dict() for n in a.workflow.nodes}
    bn = {n.node_id: n.to_dict() for n in b.workflow.nodes}
    added = sorted(set(bn) - set(an))
    removed = sorted(set(an) - set(bn))
    changed = {}
    for node_id in sorted(set(an) & set(bn)):
        if an[node_id] != bn[node_id]:
            fields = [
                k
                for k in set(an[node_id]) | set(bn[node_id])
                if an[node_id].get(k) != bn[node_id].get(k)
            ]
            changed[node_id] = sorted(fields)
    if added:
        changes["nodes_added"] = added
    if removed:
        changes["nodes_removed"] = removed
    if changed:
        changes["nodes_changed"] = changed
    a_slots = {s.name: s.to_dict() for s in a.workflow.slots}
    b_slots = {s.name: s.to_dict() for s in b.workflow.slots}
    slot_changes = {
        name for name in set(a_slots) & set(b_slots) if a_slots[name] != b_slots[name]
    }
    if set(b_slots) - set(a_slots):
        changes["slots_added"] = sorted(set(b_slots) - set(a_slots))
    if set(a_slots) - set(b_slots):
        changes["slots_removed"] = sorted(set(a_slots) - set(b_slots))
    if slot_changes:
        changes["slots_changed"] = sorted(slot_changes)
    if a.workflow.max_concurrency != b.workflow.max_concurrency:
        changes["max_concurrency"] = (a.workflow.max_concurrency, b.workflow.max_concurrency)
    return changes


def inspect_recipe(recipe: RecipeDocument) -> dict[str, Any]:
    """Human/agent-readable summary (no execution facts)."""
    return {
        "recipe_id": recipe.recipe_id,
        "name": recipe.name,
        "description": recipe.description,
        "schema_version": recipe.schema_version,
        "source_run_id": recipe.source_run_id,
        "tags": list(recipe.tags),
        "workflow_id": recipe.workflow.workflow_id,
        "nodes": [
            {
                "node_id": n.node_id,
                "action_id": n.action_id,
                "depends_on": list(n.depends_on),
                "description": n.description,
            }
            for n in recipe.workflow.nodes
        ],
        "slots": [s.to_dict() for s in recipe.workflow.slots],
        "max_concurrency": recipe.workflow.max_concurrency,
    }


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-")
    return slug or "recipe"
