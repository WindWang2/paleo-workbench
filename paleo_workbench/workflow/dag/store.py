"""WorkflowRun persistence (H3): atomic JSON checkpoints in project-managed
storage, plus the deterministic cache lookup over prior checkpoints.

The store never invents output truth: a cache hit requires (a) an identical
cache identity (action id+version, normalized parameters, input version
ids), (b) a terminal-successful node, and (c) every recorded output version
resolvable in the catalog with a passing integrity check (the catalog stays
the only artifact authority). Anything less re-executes.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from paleo_workbench.workflow.dag.model import NodeRun, RunState, WorkflowRun

logger = logging.getLogger(__name__)

_STORE_VERSION = 1


class WorkflowRunStore:
    """File-backed run store. One JSON file per run, written atomically.

    V8 M7 cache index: ``find_reusable_node`` used to JSON-parse EVERY run
    file per cacheable-node lookup (O(runs x nodes) with full
    deserialization). The store now maintains an in-memory
    ``cache_identity -> [(run_id, node_id)]`` index, built once from disk on
    first lookup and maintained incrementally on ``save`` — lookups
    deserialize only the candidate runs (newest first). The index is a
    lookup aid, never a second authority: a candidate is still re-loaded
    from its file and re-validated (state, from_cache, output resolvability)
    before reuse.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache_index: dict[str, list[tuple[str, str]]] | None = None

    # ------------------------------------------------------------ index --
    def _cache_index_entry(self, run: WorkflowRun) -> None:
        """Record one run's reusable nodes in the index (if built)."""
        if self._cache_index is None:
            return
        if run.state == RunState.RUNNING:
            return  # not reusable evidence until terminal
        for node_run in run.node_runs.values():
            if (
                node_run.state.value == "succeeded"
                and node_run.cache_identity
                and not node_run.from_cache
                and node_run.output_version_ids
            ):
                self._cache_index.setdefault(node_run.cache_identity, []).append(
                    (run.run_id, node_run.node_id)
                )

    def rebuild_cache_index(self) -> int:
        """Scan every stored run once and build the cache index.

        Returns the number of indexed node entries. Runs load through the
        normal path — a corrupted run is skipped (logged), never fatal.
        """
        self._cache_index = {}
        for run in self.list_runs():
            self._cache_index_entry(run)
        return sum(len(v) for v in self._cache_index.values())

    def candidates_for_identity(self, cache_identity: str) -> list[tuple[str, str]]:
        """(run_id, node_id) candidates for a cache identity, NEWEST first."""
        if self._cache_index is None:
            self.rebuild_cache_index()
        assert self._cache_index is not None
        entries = list(self._cache_index.get(cache_identity, []))
        entries.reverse()  # later saves appended last -> newest first
        return entries

    # ------------------------------------------------------------ CRUD --
    def _path(self, run_id: str) -> Path:
        return self.root / f"run-{run_id}.json"

    def save(self, run: WorkflowRun) -> Path:
        run.updated_at = time.time()
        path = self._path(run.run_id)
        payload = {"store_version": _STORE_VERSION, **run.to_dict()}
        fd, tmp = tempfile.mkstemp(dir=str(self.root), prefix=".tmp-run-", suffix=".json")
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
        self._cache_index_entry(run)
        return path

    def load(self, run_id: str) -> WorkflowRun:
        path = self._path(run_id)
        if not path.exists():
            raise KeyError(f"no workflow run {run_id!r} in {self.root}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # A corrupted checkpoint is never executed from: it surfaces as
            # a load failure the caller must handle (re-run from scratch).
            raise ValueError(f"workflow run {run_id!r} checkpoint is corrupted: {exc}") from exc
        return WorkflowRun.from_dict(data)

    def list_run_ids(self) -> list[str]:
        return sorted(
            p.stem.removeprefix("run-") for p in self.root.glob("run-*.json")
        )

    def list_runs(self) -> list[WorkflowRun]:
        runs = []
        for run_id in self.list_run_ids():
            try:
                runs.append(self.load(run_id))
            except Exception:  # a corrupted run must not poison cache lookups
                logger.warning("skipping unreadable workflow run %s", run_id)
        return runs


def default_store_root(context: Any) -> Path:
    """Project-managed storage root: ``<project>.artifacts/workflows/``.

    The artifacts tree is derived by the single authority
    (:func:`paleo_workbench.project.paths.artifact_dir_for`) — the same
    helper every other artifact writer uses, so workflow runs never land
    in a second tree. Falls back to a session directory when the action
    context has no project (headless unit runs).
    """
    project_path = getattr(context, "project_path", None)
    if project_path:
        from paleo_workbench.project.paths import artifact_dir_for

        root = artifact_dir_for(Path(project_path)) / "workflows"
    else:
        root = Path(tempfile.gettempdir()) / "paleo-workflow-runs"
    return root


def find_reusable_node(
    store: WorkflowRunStore,
    *,
    cache_identity: str,
    catalog: Any = None,
    verify_integrity: bool = True,
) -> NodeRun | None:
    """Search prior runs for a node with the identical cache identity whose
    outputs are still catalog-resolvable (and optionally integrity-verified).

    V8 M7: candidates come from the store's cache index (newest first) —
    only those runs are deserialized, instead of the previous full-history
    JSON rescan per lookup. Every candidate still passes the full reuse
    contract below. Returns the *prior* NodeRun (its receipt and output
    version ids are the reusable facts) or None. Corrupted/missing/deleted
    outputs never reuse.
    """
    for run_id, node_id in store.candidates_for_identity(cache_identity):
        try:
            run = store.load(run_id)
        except Exception:  # corrupted candidate — skip, keep looking
            logger.warning("cache candidate run %s unreadable; skipping", run_id)
            continue
        if run.state not in (RunState.COMPLETED, RunState.FAILED, RunState.INTERRUPTED):
            continue  # a still-running execution is not reusable evidence
        node_run = run.node_runs.get(node_id)
        if node_run is None:
            continue
        if node_run.state.value != "succeeded" or not node_run.cache_identity:
            continue
        if node_run.cache_identity != cache_identity:
            continue
        if node_run.from_cache:
            # Reuse chains to the *first* real execution; walking further
            # would compound stale-output risk for no benefit.
            continue
        if not node_run.output_version_ids:
            continue
        if catalog is not None and not _outputs_resolvable(
            catalog, node_run.output_version_ids, verify_integrity=verify_integrity
        ):
            continue
        return node_run
    return None


def run_lineage(store: WorkflowRunStore, run_id: str) -> list[str]:
    """Ancestral chain of runs (rerun/resume derivation), oldest first.

    V8 M7: [original, ..., run_id]. A malformed (cyclic) chain stops,
    never loops.
    """
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = str(run_id)
    while current is not None and current not in seen:
        seen.add(current)
        chain.append(current)
        try:
            run = store.load(current)
        except Exception:
            break
        current = run.parent_run_id
    chain.reverse()
    return chain


def _outputs_resolvable(catalog: Any, version_ids: tuple[str, ...], *, verify_integrity: bool) -> bool:
    for version_id in version_ids:
        try:
            ref = catalog.resolve_version(version_id)
        except Exception:
            return False
        if ref is None:
            return False
        if getattr(ref, "trashed", False):
            return False
        if verify_integrity and getattr(catalog, "verify_integrity", None) is not None:
            try:
                status = catalog.verify_integrity(version_id)
            except Exception:
                return False
            if getattr(status, "name", str(status)).upper() not in ("VERIFIED",):
                return False
    return True
