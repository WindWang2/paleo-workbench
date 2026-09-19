#!/usr/bin/env python3
"""Oracle fixture generator for the C++ workflow run store + reproduction
port (CONV-32, libs/workflow_engine store.cpp / reproduction.cpp).

Imports the REAL implementations (paleo_workbench.workflow.dag.model /
store / reproduction) and freezes their observable behaviour to JSON so the
C++ port can be verified against the Python chain. Regenerate with:

    python3 tools/oracle/generate_workflow_store_fixtures.py

Frozen surfaces (15 cases): save/load round-trip (to_dict + canonical
hash), the exact checkpoint FILE BYTES (indent=1, no trailing newline,
store_version first key), updated_at stamping through a patched clock, the
RunNotFound / CorruptCheckpoint message texts (store root templated as
{ROOT}), list ordering + dot-tmp invisibility, corrupt-run skipping with
the frozen warning, cache-index gates, newest-first + incremental indexing
over 30 saves, find_reusable_node hit/miss/revalidation fallbacks (fake
catalog seam), run lineage (chain / orphan / cycle), describe_reproduction
(full ordered dicts + canonical hashes, before and after a save->load
round-trip, plus the missing-node_run branches), and both
default_store_root overloads (tempdir templated as {TMP}).
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.workflow.dag import store as store_mod  # noqa: E402
from paleo_workbench.workflow.dag.model import (  # noqa: E402
    NodeRun,
    NodeState,
    RunState,
    WorkflowRun,
    WorkflowSpec,
    canonical_hash,
)
from paleo_workbench.workflow.dag.reproduction import describe_reproduction  # noqa: E402
from paleo_workbench.workflow.dag.store import (  # noqa: E402
    WorkflowRunStore,
    default_store_root,
    find_reusable_node,
    run_lineage,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_engine"
    / "workflow_engine_tests"
    / "fixtures"
    / "workflow_store_oracle.json"
)

# The spec is frozen as a plain dict; BOTH sides build it through
# WorkflowSpec.from_dict(same dict) so the parsed spec (and spec_hash) is
# identical by construction.
SPEC_DICT = {
    "workflow_id": "wf-store-parity",
    "name": "Store Parity Spec",
    "description": "CONV-32 store oracle spec",
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
}

MINI_SPEC_DICT = {
    "workflow_id": "wf-mini",
    "name": "Mini",
    "description": "",
    "max_concurrency": 1,
    "schema_version": "1.0",
    "slots": [],
    "nodes": [
        {
            "node_id": "solo",
            "action_id": "test.noop",
            "parameters": {},
            "depends_on": [],
            "condition": None,
            "retry": {"max_attempts": 1, "backoff_seconds": 0.0},
            "description": "",
        }
    ],
}

RICH_RUN_ID = "aaaabbbbccccdddd"
RICH_SLOTS = {"horizon": "H2", "grid_n": 16}
CORRUPT_TEXT = "{corrupted"


# --------------------------------------------------------------- clocks --
class FixedClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class SeqClock:
    """Deterministic time.time() stand-in: base + n*step per call."""

    def __init__(self, base: float, step: float = 1.0) -> None:
        self.base = base
        self.step = step
        self.calls = 0

    def __call__(self) -> float:
        value = self.base + self.calls * self.step
        self.calls += 1
        return value


class patched_time:
    """Point store.py's `time.time` (and everything else using the time
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


# ---------------------------------------------------------------- runs --
def make_rich_run(spec: WorkflowSpec) -> WorkflowRun:
    run = WorkflowRun.create(spec, dict(RICH_SLOTS))
    run.run_id = RICH_RUN_ID
    run.created_at = 1000.0
    run.updated_at = 1000.0
    run.project_name = "Demo Project"
    run.project_path = "/opt/fake/demo.paleo.json"
    run.state = RunState.COMPLETED
    ex = run.node_runs["extract"]
    ex.state = NodeState.SUCCEEDED
    ex.attempt = 1
    ex.action_status = "ok"
    ex.cache_identity = "ident-rich-extract"
    ex.input_version_ids = ()
    ex.output_version_ids = ("ver-extract-0001",)
    ex.parameters = {
        "factor_name": "gr",
        "target_horizon": "H2",
        "nested": {"k": [1, 2.5, "ü"]},
    }
    ex.outputs = {"point_count": 3}
    ex.receipt = {
        "provider_id": "prov://native/extract",
        "provider_version": "1.2.3",
        "action_version": "4.5.6",
        "cache_identity": "ident-receipt-extract",
        "environment": {
            "python": "3.11.9",
            "platform": "linux",
            "build": "par0",
        },
    }
    ex.started_at = 1000.5
    ex.finished_at = 1001.25
    it = run.node_runs["interp"]
    it.state = NodeState.SUCCEEDED
    it.attempt = 2
    it.from_cache = True
    it.cache_identity = "ident-rich-interp"
    it.input_version_ids = ("ver-extract-0001",)
    it.output_version_ids = ("ver-interp-0002",)
    it.parameters = {"samples": [], "grid_n": 16}
    it.outputs = {"grid_z": [[1.0, 2.0]]}
    # "report" stays PENDING (create() seeded it).
    return run


def mini_run(spec: WorkflowSpec, run_id: str, now: float = 1000.0) -> WorkflowRun:
    run = WorkflowRun.create(spec, {})
    run.run_id = run_id
    run.created_at = now
    run.updated_at = now
    return run


def succeed_solo(run: WorkflowRun, identity: str, outputs, **fields) -> WorkflowRun:
    run.state = RunState.COMPLETED
    solo = run.node_runs["solo"]
    solo.state = NodeState.SUCCEEDED
    solo.attempt = 1
    solo.cache_identity = identity
    solo.output_version_ids = tuple(outputs)
    for key, value in fields.items():
        setattr(solo, key, value)
    return run


# -------------------------------------------------------------- catalog --
class FakeVersionRef:
    def __init__(self, trashed: bool = False) -> None:
        self.trashed = trashed


class FakeIntegrityStatus:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeCatalog:
    """Duck-typed catalog seam mirroring the C++ CatalogLike contract."""

    def __init__(self, resolved: dict, integrity=None) -> None:
        # resolved: version_id -> FakeVersionRef | None (unresolvable)
        self._resolved = resolved
        self._integrity = integrity  # None == no verify_integrity attr

    def resolve_version(self, version_id: str):
        if version_id not in self._resolved:
            raise KeyError(f"unknown version {version_id!r}")
        return self._resolved[version_id]

    def verify_integrity(self, version_id: str):
        if self._integrity is None:
            raise AttributeError("no verify_integrity")
        name = self._integrity.get(version_id, "verified")
        return FakeIntegrityStatus(name)


# ------------------------------------------------------------- capture --
class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def capture_store_logger() -> ListHandler:
    handler = ListHandler()
    logger = logging.getLogger("paleo_workbench.workflow.dag.store")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    return handler


def main() -> None:
    spec = WorkflowSpec.from_dict(SPEC_DICT)
    mini = WorkflowSpec.from_dict(MINI_SPEC_DICT)
    doc = {
        "python": {
            "generator": "tools/oracle/generate_workflow_store_fixtures.py",
            "modules": [
                "paleo_workbench.workflow.dag.model",
                "paleo_workbench.workflow.dag.store",
                "paleo_workbench.workflow.dag.reproduction",
            ],
        },
        "spec": SPEC_DICT,
        "spec_hash": spec.spec_hash,
        "mini_spec": MINI_SPEC_DICT,
        "mini_spec_hash": mini.spec_hash,
        "rich_run_id": RICH_RUN_ID,
        "rich_slot_values": RICH_SLOTS,
    }

    # ------------------------------------------------ 1. roundtrip --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c01-"))
    store = WorkflowRunStore(root)
    run = make_rich_run(spec)
    with patched_time(FixedClock(2000.0)):
        store.save(run)
    loaded = store.load(RICH_RUN_ID)
    saved_dict = run.to_dict()  # after save -> updated_at stamped
    loaded_dict = loaded.to_dict()
    assert saved_dict == loaded_dict, "case01 rich run must round-trip equal"
    doc["case01_roundtrip"] = {
        "saved_to_dict": saved_dict,
        "loaded_to_dict": loaded_dict,
        "saved_hash": canonical_hash(saved_dict),
        "loaded_hash": canonical_hash(loaded_dict),
    }

    # ------------------------------------------------ 2. file format --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c02-"))
    store = WorkflowRunStore(root)
    run = make_rich_run(spec)
    with patched_time(FixedClock(2000.0)):
        path = store.save(run)
    text = path.read_text(encoding="utf-8")
    assert not text.endswith("\n"), "checkpoint must have NO trailing newline"
    payload = json.loads(text)
    doc["case02_file_format"] = {
        "text": text,
        "top_keys": list(payload.keys()),
        "workflow_keys": list(payload["workflow"].keys()),
        "node_run_keys": list(payload["node_runs"][0].keys()),
        "store_version": payload["store_version"],
    }
    assert doc["case02_file_format"]["top_keys"][0] == "store_version"

    # ---------------------------------------------- 3. updated_at stamp --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c03-"))
    store = WorkflowRunStore(root)
    run = make_rich_run(spec)  # created_at = 1000.0
    assert run.created_at == 1000.0
    with patched_time(FixedClock(2000.5)):
        store.save(run)
    stamped = store.load(RICH_RUN_ID).updated_at
    doc["case03_updated_at"] = {
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "updated_ge_created": run.updated_at >= run.created_at,
        "stamped_in_file": stamped,
    }

    # ------------------------------------------------- 4. load missing --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c04-"))
    store = WorkflowRunStore(root)
    try:
        store.load("ghost")
        raise AssertionError("load(missing) must raise")
    except KeyError as exc:
        message = str(exc.args[0])
    doc["case04_missing"] = {
        "run_id": "ghost",
        "message": message.replace(str(root), "{ROOT}"),
    }
    assert "{ROOT}" in doc["case04_missing"]["message"]

    # ------------------------------------------------ 5. load corrupt --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c05-"))
    store = WorkflowRunStore(root)
    (root / "run-bad1.json").write_text(CORRUPT_TEXT, encoding="utf-8")
    try:
        store.load("bad1")
        raise AssertionError("load(corrupt) must raise")
    except ValueError as exc:
        message = str(exc)
    doc["case05_corrupt"] = {
        "run_id": "bad1",
        "raw": CORRUPT_TEXT,
        # Only the prefix is frozen: the parser detail after the colon is
        # CPython-specific (nlohmann words its parse errors differently).
        "message_prefix": message.split(":", 1)[0] + ":",
        "python_detail": message,
    }

    # ------------------------------------- 6. list ids + tmp invisible --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c06-"))
    store = WorkflowRunStore(root)
    clock = SeqClock(1500.0)
    with patched_time(clock):
        for run_id in ("b", "a", "c"):
            store.save(mini_run(mini, run_id))
    (root / ".tmp-run-junk.json").write_text("{}", encoding="utf-8")
    doc["case06_list_ids"] = {"ids": store.list_run_ids()}

    # ------------------------------------------- 7. list_runs skips bad --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c07-"))
    store = WorkflowRunStore(root)
    handler = capture_store_logger()
    with patched_time(SeqClock(1600.0)):
        store.save(mini_run(mini, "good"))
    (root / "run-zcorrupt.json").write_text(CORRUPT_TEXT, encoding="utf-8")
    runs = store.list_runs()
    doc["case07_list_runs"] = {
        "ids": [r.run_id for r in runs],
        "warnings": list(handler.messages),  # copy: the handler stays attached
    }

    # ------------------------------------------------- 8. index gates --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c08-"))
    store = WorkflowRunStore(root)
    with patched_time(SeqClock(1700.0)):
        # RUNNING run with a succeeded node: not reusable evidence yet.
        running_run = succeed_solo(mini_run(mini, "gaterunning"), "ident-gates", ["v-x"])
        running_run.state = RunState.RUNNING
        store.save(running_run)
    cached_run = succeed_solo(
        mini_run(mini, "gatecached"), "ident-gates", ["v-x"], from_cache=True
    )
    empty_run = succeed_solo(mini_run(mini, "gateempty"), "ident-gates", [])
    good_run = succeed_solo(mini_run(mini, "goodrun"), "ident-gates", ["v-good-1"])
    with patched_time(SeqClock(1710.0)):
        store.save(cached_run)
        store.save(empty_run)
        store.save(good_run)
    count = store.rebuild_cache_index()
    doc["case08_index_gates"] = {
        "identity": "ident-gates",
        "rebuild_count": count,
        "candidates": [list(p) for p in store.candidates_for_identity("ident-gates")],
        "empty_identity_candidates": [
            list(p) for p in store.candidates_for_identity("ident-none")
        ],
    }

    # ------------------------------------ 9. newest-first + incremental --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c09-"))
    store = WorkflowRunStore(root)
    clock = SeqClock(3000.0)
    with patched_time(clock):
        for i in range(30):
            run_id = f"r{i:02d}"
            store.save(
                succeed_solo(mini_run(mini, run_id), "ident-many", [f"ver-{run_id}"])
            )
    initial = store.candidates_for_identity("ident-many")  # lazy build
    r99 = succeed_solo(mini_run(mini, "r99"), "ident-many", ["ver-r99"])
    with patched_time(FixedClock(4000.0)):
        store.save(r99)  # incremental index update post-build
    after = store.candidates_for_identity("ident-many")
    reusable = find_reusable_node(store, cache_identity="ident-many")
    assert reusable is not None
    doc["case09_many"] = {
        "identity": "ident-many",
        "count": 30,
        "initial_head": list(initial[0]),
        "initial_len": len(initial),
        "after_r99_head": list(after[0]),
        "after_r99_len": len(after),
        "reusable_run": "r99",
        "reusable_node": reusable.to_dict(),
    }

    # --------------------------------------------------- 10. pure miss --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c10-"))
    store = WorkflowRunStore(root)
    with patched_time(FixedClock(1800.0)):
        store.save(succeed_solo(mini_run(mini, "onlyrun"), "ident-only", ["v-o"]))
    found = find_reusable_node(store, cache_identity="ident-none")
    doc["case10_miss"] = {"identity": "ident-none", "found": found is not None}

    # ------------------------------------------- 11. revalidation paths --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c11-"))
    store = WorkflowRunStore(root)
    with patched_time(FixedClock(2100.0)):
        store.save(succeed_solo(mini_run(mini, "fbnew"), "ident-fb", ["v-new"]))
    with patched_time(FixedClock(2000.0)):
        store.save(succeed_solo(mini_run(mini, "fbold"), "ident-fb", ["v-old"]))
    catalog_fb = FakeCatalog(
        {"v-new": None, "v-old": FakeVersionRef(False)},
        integrity={},  # verify_integrity present -> "verified"
    )
    fb = find_reusable_node(store, cache_identity="ident-fb", catalog=catalog_fb)
    assert fb is not None
    # from_cache-only identity: never indexed -> no candidates at all.
    with patched_time(FixedClock(2200.0)):
        fc = succeed_solo(mini_run(mini, "fconly"), "ident-fc", ["v-x"])
        fc.node_runs["solo"].from_cache = True
        store.save(fc)
    fc_found = find_reusable_node(store, cache_identity="ident-fc")
    # trashed output: resolvable but trashed -> not reusable.
    with patched_time(FixedClock(2300.0)):
        store.save(succeed_solo(mini_run(mini, "trashrun"), "ident-trash", ["v-trash"]))
    catalog_trash = FakeCatalog({"v-trash": FakeVersionRef(True)})
    trash_found = find_reusable_node(
        store, cache_identity="ident-trash", catalog=catalog_trash
    )
    # integrity status below VERIFIED blocks reuse...
    with patched_time(FixedClock(2400.0)):
        store.save(
            succeed_solo(mini_run(mini, "intfailrun"), "ident-intfail", ["v-int"])
        )
    catalog_intfail = FakeCatalog(
        {"v-int": FakeVersionRef(False)}, integrity={"v-int": "FAILED"}
    )
    intfail_found = find_reusable_node(
        store, cache_identity="ident-intfail", catalog=catalog_intfail
    )
    # ...but verify_integrity=False skips the check entirely.
    intfail_off = find_reusable_node(
        store, cache_identity="ident-intfail", catalog=catalog_intfail,
        verify_integrity=False,
    )
    assert intfail_off is not None
    # resolve_version raising -> unresolvable.
    catalog_raise = FakeCatalog({})
    raise_found = find_reusable_node(
        store, cache_identity="ident-fb", catalog=catalog_raise
    )
    # newest candidate unreadable on disk (corrupted after save) -> older
    # candidate wins. NOTE: the incremental index orders by SAVE order, so
    # cbad must be saved LAST to sit newest in the reversed candidate walk.
    with patched_time(FixedClock(2450.0)):
        store.save(succeed_solo(mini_run(mini, "cgood"), "ident-corrupt", ["v-c2"]))
    with patched_time(FixedClock(2500.0)):
        store.save(succeed_solo(mini_run(mini, "cbad"), "ident-corrupt", ["v-c1"]))
    (root / "run-cbad.json").write_text(CORRUPT_TEXT, encoding="utf-8")
    handler2 = capture_store_logger()
    corrupt_fb = find_reusable_node(store, cache_identity="ident-corrupt")
    assert corrupt_fb is not None
    doc["case11_revalidation"] = {
        "identity": "ident-fb",
        "fallback_run": "fbold",
        "fallback_node": fb.to_dict(),
        "from_cache_only_identity": "ident-fc",
        "from_cache_only_found": fc_found is not None,
        "trashed_found": trash_found is not None,
        "integrity_found": intfail_found is not None,
        "verify_off_found": intfail_off is not None,
        "verify_off_node": intfail_off.to_dict(),
        "resolve_raising_found": raise_found is not None,
        "corrupt_identity": "ident-corrupt",
        "corrupt_fallback_run": "cgood",
        "corrupt_fallback_node": corrupt_fb.to_dict(),
        "corrupt_candidate_warnings": list(handler2.messages),
    }

    # ------------------------------------------------- 12. lineage --
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c12-"))
    store = WorkflowRunStore(root)
    orig = mini_run(mini, "orig", now=1000.0)
    child = mini_run(mini, "child", now=1001.0)
    child.parent_run_id = "orig"
    grand = mini_run(mini, "grandchild", now=1002.0)
    grand.parent_run_id = "child"
    orphan = mini_run(mini, "orphan", now=1003.0)
    orphan.parent_run_id = "vanished"
    acyc = mini_run(mini, "acyc", now=1004.0)
    acyc.parent_run_id = "bcyc"
    bcyc = mini_run(mini, "bcyc", now=1005.0)
    bcyc.parent_run_id = "acyc"
    with patched_time(SeqClock(2600.0)):
        for run_ in (orig, child, grand, orphan, acyc, bcyc):
            store.save(run_)
    doc["case12_lineage"] = {
        "grandchild": run_lineage(store, "grandchild"),
        "orphan": run_lineage(store, "orphan"),
        "cycle_from_acyc": run_lineage(store, "acyc"),
        "parent_after_roundtrip": store.load("grandchild").parent_run_id,
    }

    # --------------------------------------- 13. describe_reproduction --
    run = make_rich_run(spec)
    describe_pre = describe_reproduction(run)
    root = Path(tempfile.mkdtemp(prefix="pwb-store-c13-"))
    store = WorkflowRunStore(root)
    with patched_time(FixedClock(2000.0)):
        store.save(run)
    describe_post = describe_reproduction(store.load(RICH_RUN_ID))
    assert describe_pre == describe_post, "describe must be round-trip stable"
    doc["case13_reproduction"] = {
        "describe": describe_pre,
        "hash": canonical_hash(describe_pre),
        "describe_after_roundtrip": describe_post,
        "hash_after_roundtrip": canonical_hash(describe_post),
    }

    # -------------------------------------- 14. describe on empty run --
    empty = WorkflowRun.create(mini, {})
    empty.run_id = "ffffffffffffffff"
    empty.created_at = 1000.0
    empty.updated_at = 1000.0
    describe_empty = describe_reproduction(empty)
    del empty.node_runs["solo"]  # exercise the missing-node_run branches
    describe_missing = describe_reproduction(empty)
    doc["case14_empty"] = {
        "describe": describe_empty,
        "hash": canonical_hash(describe_empty),
        "describe_missing_node": describe_missing,
    }

    # ------------------------------------------ 15. default_store_root --
    with_project = default_store_root(
        SimpleNamespace(project_path="/opt/fake/demo.paleo.json")
    )
    no_project = default_store_root(SimpleNamespace())
    doc["case15_default_root"] = {
        "project_arg": "/opt/fake/demo.paleo.json",
        "with_project": str(with_project),
        "no_project": str(no_project).replace(
            str(tempfile.gettempdir()), "{TMP}"
        ),
    }
    assert "{TMP}" in doc["case15_default_root"]["no_project"]

    target = OUT
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"wrote {target} ({target.stat().st_size} bytes, 15 oracle cases, "
        f"spec_hash {doc['spec_hash'][:12]}...)"
    )


if __name__ == "__main__":
    main()
