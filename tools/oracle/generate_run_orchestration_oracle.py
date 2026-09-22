#!/usr/bin/env python3
"""Freeze catalog/lifecycle.py run-orchestration skeleton semantics.

Drives the shared helpers every register_*_run composes — _fail_run,
_annotate_output_port/_annotate_input_ports, resolve_input_versions,
_versions_for_domain_tasks — plus register_factor_map_run as the
canonical full skeleton (begin → register_intermediate → complete /
fail-compensation). Replayed by
workflow_runtime_tests/run_orchestration_test.cpp.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.catalog import lifecycle  # noqa: E402
from paleo_workbench.project.models import FactorMapTask  # noqa: E402

OUT = (
    ROOT
    / "libs/workflow_runtime/workflow_runtime_tests/fixtures"
    / "run_orchestration_oracle.json"
)


# ---------------------------------------------------------------- fake port


@dataclass
class FakeVersion:
    version_id: str
    trashed: bool = False


@dataclass
class FakeRun:
    run_id: str
    domain_task_id: str | None = None
    status: str = "running"
    input_version_ids: list[str] = field(default_factory=list)
    output_version_ids: list[str] = field(default_factory=list)


class FakeCatalog:
    """CatalogPort surface the lifecycle helpers touch; records calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.runs: list[FakeRun] = []
        self.legacy: dict[str, FakeVersion] = {}
        self.versions: dict[str, FakeVersion] = {}
        self.next_run = 0
        self.next_version = 0
        self.raise_on: set[str] = set()

    def _maybe_raise(self, op: str) -> None:
        if op in self.raise_on:
            raise RuntimeError(f"{op} refused")

    def begin_run(self, **kwargs):
        self._maybe_raise("begin_run")
        self.next_run += 1
        run = FakeRun(run_id=f"run_{self.next_run:04d}")
        run.input_version_ids = list(kwargs.get("input_version_ids") or [])
        run.domain_task_id = kwargs.get("domain_task_id")
        self.runs.append(run)
        self.calls.append({"op": "begin_run", "kwargs": kwargs})
        return run

    def complete_run(self, run_id, *, status="complete", **kwargs):
        self._maybe_raise("complete_run")
        for r in self.runs:
            if r.run_id == run_id:
                r.status = status
        self.calls.append(
            {"op": "complete_run", "run_id": run_id, "status": status,
             "kwargs": kwargs}
        )

    def register_intermediate(self, **kwargs):
        self._maybe_raise("register_intermediate")
        self.next_version += 1
        ref = FakeVersion(version_id=f"ver_{self.next_version:04d}")
        self.calls.append({"op": "register_intermediate", "kwargs": kwargs})
        return ref

    def set_run_ports(self, run_id, *, input_ports=None, output_ports=None):
        self._maybe_raise("set_run_ports")
        self.calls.append(
            {"op": "set_run_ports", "run_id": run_id,
             "input_ports": input_ports, "output_ports": output_ports}
        )

    def resolve_legacy_resource(self, resource_id):
        return self.legacy.get(resource_id)

    def list_runs(self):
        return list(self.runs)

    def resolve_version(self, version_id):
        return self.versions.get(version_id)


# ------------------------------------------------------------------ cases


def case_resolve_input_versions() -> dict:
    cat = FakeCatalog()
    cat.legacy["res_a"] = FakeVersion("ver_a")
    cat.legacy["res_b"] = FakeVersion("ver_b")
    got = lifecycle.resolve_input_versions(
        ["res_a", "res_missing", "res_b"], catalog=cat
    )
    empty = lifecycle.resolve_input_versions([], catalog=cat)
    return {"resolved": got, "empty": empty}


def case_fail_run() -> dict:
    cat = FakeCatalog()
    run = cat.begin_run(operation="op")
    lifecycle._fail_run(cat, run.run_id)
    status_after = run.status
    # Backend failure must be swallowed.
    cat2 = FakeCatalog()
    cat2.raise_on.add("complete_run")
    run2 = cat2.begin_run(operation="op")
    lifecycle._fail_run(cat2, run2.run_id)  # must not raise
    lifecycle._fail_run(cat2, None)  # None → early return, no call
    return {
        "status_after": status_after,
        "calls_when_raising": cat2.calls,
    }


def case_annotate_output_port() -> dict:
    cat = FakeCatalog()
    lifecycle._annotate_output_port(cat, "run_1", "ver_9", "primary")
    # None args → no call.
    lifecycle._annotate_output_port(cat, None, "ver_9", "primary")
    lifecycle._annotate_output_port(cat, "run_1", None, "primary")
    calls_ok = cat.calls
    # Backend failure swallowed.
    cat2 = FakeCatalog()
    cat2.raise_on.add("set_run_ports")
    lifecycle._annotate_output_port(cat2, "run_1", "ver_9", "primary")
    return {"calls": calls_ok, "raising_calls": cat2.calls}


def case_annotate_input_ports() -> dict:
    cat = FakeCatalog()
    lifecycle._annotate_input_ports(
        cat, "run_1", ["ver_a", "ver_b"], "source",
        entity_type="well", entity_ids=["w1"],
    )
    lifecycle._annotate_input_ports(cat, "run_1", [], "source")
    lifecycle._annotate_input_ports(cat, None, ["ver_a"], "source")
    calls_ok = cat.calls
    cat2 = FakeCatalog()
    cat2.raise_on.add("set_run_ports")
    lifecycle._annotate_input_ports(cat2, "run_1", ["ver_a"], "source")
    return {"calls": calls_ok, "raising_calls": cat2.calls}


def _run(tid, status, inputs=(), outputs=()):
    return FakeRun(
        run_id=f"r_{tid}_{status}",
        domain_task_id=tid,
        status=status,
        input_version_ids=list(inputs),
        output_version_ids=list(outputs),
    )


def case_versions_for_domain_tasks() -> dict:
    cat = FakeCatalog()
    # Insertion order matters: task_b first.
    cat.runs = [
        _run("task_b", "complete", inputs=["in_b"], outputs=["out_b"]),
        _run("task_a", "complete", inputs=["in_a"], outputs=[]),
        _run("task_a", "complete", inputs=["in_a2"], outputs=["out_a2"]),
        _run("task_b", "failed", inputs=["in_bx"], outputs=["out_bx"]),
        _run("task_b", "complete", inputs=["in_b2"], outputs=["out_b2"]),
        _run("task_c", "complete", inputs=["in_c"], outputs=["out_c"]),
    ]
    cat.versions = {
        "out_b": FakeVersion("out_b"),
        "out_a2": FakeVersion("out_a2"),
        "out_b2": FakeVersion("out_b2", trashed=True),
        "out_c": FakeVersion("out_c"),
    }
    got = lifecycle._versions_for_domain_tasks(
        ["task_a", "task_b", "task_c"], catalog=cat
    )
    subset = lifecycle._versions_for_domain_tasks(["task_a"], catalog=cat)
    empty = lifecycle._versions_for_domain_tasks([], catalog=cat)
    # Catalog errors PROPAGATE from the helper — the `except Exception:
    # return []` wrapper lives in _resolve_map_input_ids (caller-side).
    class BoomCatalog(FakeCatalog):
        def list_runs(self):
            raise RuntimeError("catalog down")

    boom = None
    try:
        lifecycle._versions_for_domain_tasks(["task_a"], catalog=BoomCatalog())
    except RuntimeError as exc:
        boom = str(exc)
    return {
        "resolved": got, "subset": subset, "empty": empty, "boom": boom
    }


def case_factor_map_run() -> dict:
    out: dict = {}

    def make_task() -> FactorMapTask:
        return FactorMapTask(
            id="fmt_1",
            name="孔隙度成图",
            target_horizon="H1",
            factor_type="porosity",
            method="idw",
            input_resource_ids=["res_a", "res_missing"],
            input_snapshot_hash="snap123",
            generator_version="gen-v9",
        )

    # Happy path with intermediate artifact.
    cat = FakeCatalog()
    cat.legacy["res_a"] = FakeVersion("ver_res_a")
    task = make_task()
    run, version = lifecycle.register_factor_map_run(
        task, catalog=cat, intermediate_path="artifacts/grid.npz",
        intermediate_checksum="abc",
        extra_input_version_ids=["ver_res_a", "ver_extra"],
    )
    out["with_intermediate"] = {
        "run_id": run.run_id if run else None,
        "version_id": version.version_id if version else None,
        "run_status": run.status,
        "calls": cat.calls,
    }

    # No intermediate → run completes with no version.
    cat = FakeCatalog()
    cat.legacy["res_a"] = FakeVersion("ver_res_a")
    run, version = lifecycle.register_factor_map_run(
        make_task(), catalog=cat
    )
    out["no_intermediate"] = {
        "run_id": run.run_id if run else None,
        "version_id": version.version_id if version else None,
        "run_status": run.status,
        "calls": cat.calls,
    }

    # Project horizon-interpretation auto-collect (key match + name match).
    cat = FakeCatalog()
    project = SimpleNamespace(
        horizon_interpretations=[
            SimpleNamespace(horizon_key="H1", name="异名",
                            current_version_id="ver_interp_key"),
            SimpleNamespace(horizon_key="HX", name="H1",
                            current_version_id="ver_interp_name"),
            SimpleNamespace(horizon_key="HX", name="其他",
                            current_version_id="ver_interp_skip"),
            SimpleNamespace(horizon_key="H1", name="异名",
                            current_version_id=None),
        ]
    )
    run, _ = lifecycle.register_factor_map_run(
        make_task(), catalog=cat, project=project
    )
    out["horizon_collect"] = {
        "input_version_ids": run.input_version_ids,
    }

    # Failure: register_intermediate raises → run marked failed, re-raise.
    cat = FakeCatalog()
    cat.raise_on.add("register_intermediate")
    raised = None
    run_ids_before = None
    try:
        lifecycle.register_factor_map_run(
            make_task(), catalog=cat,
            intermediate_path="artifacts/grid.npz",
        )
    except RuntimeError as exc:
        raised = str(exc)
    run_ids_before = [r.status for r in cat.runs]
    out["intermediate_failure"] = {
        "raised": raised,
        "run_statuses": run_ids_before,
        "calls": cat.calls,
    }

    # complete_run raising inside _fail_run → still re-raises original.
    cat = FakeCatalog()
    cat.raise_on.update({"register_intermediate", "complete_run"})
    raised2 = None
    try:
        lifecycle.register_factor_map_run(
            make_task(), catalog=cat,
            intermediate_path="artifacts/grid.npz",
        )
    except RuntimeError as exc:
        raised2 = str(exc)
    out["fail_run_swallow"] = {"raised": raised2, "calls": cat.calls}
    return out


def main() -> int:
    cases = {
        "resolve_input_versions": case_resolve_input_versions(),
        "fail_run": case_fail_run(),
        "annotate_output_port": case_annotate_output_port(),
        "annotate_input_ports": case_annotate_input_ports(),
        "versions_for_domain_tasks": case_versions_for_domain_tasks(),
        "factor_map_run": case_factor_map_run(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
