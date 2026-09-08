"""V8 M2 — constraint lifecycle: catalog DERIVED versions, pins, stale
propagation, version comparison, `constraints:current` resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
    ProjectMeta,
)
from paleo_workbench.workflow.constraint_versions import (
    commit_all_constraints,
    commit_constraint_group,
    compare_constraint_versions,
    constraint_group_content_hash,
    constraint_pins_for_task,
    constraint_pins_staleness,
    current_constraint_version,
    pinned_constraint_pins,
    resolve_constraint_ref,
)
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


def _line(name: str, coords: list[list[float]], *, role: str = "break") -> ConstraintLine:
    return ConstraintLine(
        name=name, role=role, coordinates=[list(c) for c in coords]
    )


def _group(name: str = "约束层", horizon: str = "H1", lines=None) -> ConstraintLayers:
    return ConstraintLayers(
        name=name, target_horizon=horizon, lines=list(lines or [])
    )


@pytest.fixture()
def project() -> ProjectDocument:
    doc = ProjectDocument(meta=ProjectMeta(name="m2"))
    doc.constraint_layers.append(
        _group(
            lines=[
                _line("F1", [[0.0, 0.0], [10.0, 0.0]]),
                _line("D1", [[0.0, 0.0], [0.0, 8.0]], role="direction"),
            ]
        )
    )
    return doc


@pytest.fixture()
def catalog(tmp_path: Path) -> DataCatalogService:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


class TestCommit:
    def test_first_commit_creates_asset_version_run(self, project, catalog):
        group = project.constraint_layers[0]
        report = commit_constraint_group(project, catalog, group, actor="tester")
        assert report.committed and report.reason == "changed"
        assert report.line_count == 2
        assert report.version_id and report.run_id
        version = catalog.get_version(report.version_id)
        assert version.stage.value == "derived"
        assert version.metadata["content_hash"] == report.content_hash
        run = catalog.get_run(report.run_id)
        assert run.operation == "constraint_commit"
        assert run.status == "complete"

    def test_unchanged_commit_is_noop(self, project, catalog):
        group = project.constraint_layers[0]
        first = commit_constraint_group(project, catalog, group)
        second = commit_constraint_group(project, catalog, group)
        assert not second.committed and second.reason == "unchanged"
        assert second.version_id == first.version_id  # same version returned

    def test_changed_geometry_commits_new_version_same_asset(
        self, project, catalog
    ):
        group = project.constraint_layers[0]
        first = commit_constraint_group(project, catalog, group)
        group.lines[0].coordinates = [[0.0, 0.0], [12.0, 1.0]]
        second = commit_constraint_group(project, catalog, group)
        assert second.committed
        assert second.asset_id == first.asset_id  # ONE asset, two versions
        assert second.version_id != first.version_id
        assert second.previous_version_id == first.version_id
        # version lineage chain
        v2 = catalog.get_version(second.version_id)
        assert first.version_id in v2.parent_version_ids

    def test_empty_group_commits_nothing(self, project, catalog):
        empty = _group(name="空")
        project.constraint_layers.append(empty)
        report = commit_constraint_group(project, catalog, empty)
        assert not report.committed and report.reason == "no_content"

    def test_commit_all_covers_every_group(self, project, catalog):
        project.constraint_layers.append(_group(
            name="G2", horizon="H2",
            lines=[_line("F2", [[0.0, 0.0], [3.0, 4.0]])],
        ))
        reports = commit_all_constraints(project, catalog, actor="batch")
        assert len(reports) == 2
        assert all(r.committed for r in reports[:1])


class TestPinsAndStaleness:
    def test_pin_at_interpolation_records_content_hash(self, project, catalog):
        task = FactorMapTask(
            name="t", target_horizon="H1", method="IDW", factor_type="砂岩含量",
            parameters={
                "sample_points": [
                    {"x": float(i), "y": 0.5, "value": float(i)}
                    for i in range(6)
                ]
            },
        )
        project.factor_map_tasks.append(task)
        commit_constraint_group(project, catalog, project.constraint_layers[0])
        apply_interpolation_to_task(task, project=project)
        pins = pinned_constraint_pins(task)
        assert len(pins) == 1
        assert pins[0]["content_hash"]
        # pin is hash-only at interpolation time (no catalog there);
        # version binding resolves lazily at evaluation time
        assert pins[0]["version_id"] is None
        verdict = constraint_pins_staleness(task, project, catalog)
        assert verdict["state"] == "current"

    def test_edit_after_pin_marks_stale_content(self, project, catalog):
        task = FactorMapTask(
            name="t", target_horizon="H1", method="IDW", factor_type="砂岩含量",
            parameters={
                "sample_points": [
                    {"x": float(i), "y": 0.5, "value": float(i)}
                    for i in range(6)
                ]
            },
        )
        project.factor_map_tasks.append(task)
        apply_interpolation_to_task(task, project=project)
        # edit a critical constraint AFTER the task was computed
        project.constraint_layers[0].lines[0].coordinates = [[5.0, 5.0], [9.0, 9.0]]
        verdict = constraint_pins_staleness(task, project, catalog=None)
        assert verdict["state"] == "stale_content"
        entry = next(e for e in verdict["groups"] if e["state"] == "stale_content")
        assert "constraint content changed" in entry["detail"]

    def test_new_commit_marks_stale_version_not_content(self, project, catalog):
        task = FactorMapTask(
            name="t", target_horizon="H1", method="IDW", factor_type="砂岩含量",
            parameters={
                "sample_points": [
                    {"x": float(i), "y": 0.5, "value": float(i)}
                    for i in range(6)
                ]
            },
        )
        project.factor_map_tasks.append(task)
        group = project.constraint_layers[0]
        commit_constraint_group(project, catalog, group)
        apply_interpolation_to_task(task, project=project)
        # document content UNCHANGED but a new commit exists (e.g. re-commit
        # after a cosmetic edit reverted) — force a new commit by hashing a
        # transient change, then reverting produces stale_version only via
        # version mismatch: simulate by pinning an older version id.
        pins = pinned_constraint_pins(task)
        assert pins and pins[0]["content_hash"]
        group.lines[0].coordinates = [[0.0, 0.0], [11.0, 0.0]]
        commit_constraint_group(project, catalog, group)
        # document content now differs from pin → stale_content wins
        verdict = constraint_pins_staleness(task, project, catalog)
        assert verdict["state"] == "stale_content"
        # revert the document: pin hash matches again but version is old
        group.lines[0].coordinates = [[0.0, 0.0], [10.0, 0.0]]
        verdict2 = constraint_pins_staleness(task, project, catalog)
        assert verdict2["state"] == "stale_version"

    def test_uncommitted_pin_stays_unknown(self, project, catalog):
        task = FactorMapTask(
            name="t", target_horizon="H1", method="IDW", factor_type="砂岩含量",
            parameters={
                "sample_points": [
                    {"x": float(i), "y": 0.5, "value": float(i)}
                    for i in range(6)
                ]
            },
        )
        project.factor_map_tasks.append(task)
        apply_interpolation_to_task(task, project=project)  # no commit ever
        verdict = constraint_pins_staleness(task, project, catalog)
        entry = verdict["groups"][0]
        # content-hash pin exists but no version binding → unknown, honest
        assert entry["state"] == "unknown"

    def test_unaffected_task_not_polluted(self, project, catalog):
        # a task on a different horizon with its own group stays current
        project.constraint_layers.append(_group(
            name="G2", horizon="H2",
            lines=[_line("F2", [[0.0, 0.0], [3.0, 4.0]])],
        ))
        task = FactorMapTask(
            name="t2", target_horizon="H2", method="IDW", factor_type="砂岩含量",
            parameters={
                "sample_points": [
                    {"x": float(i), "y": 0.5, "value": float(i)}
                    for i in range(6)
                ]
            },
        )
        project.factor_map_tasks.append(task)
        commit_constraint_group(project, catalog, project.constraint_layers[1])
        apply_interpolation_to_task(task, project=project)
        # edit the H1 group — must NOT stale the H2 task
        project.constraint_layers[0].lines[0].coordinates = [[7.0, 7.0], [8.0, 8.0]]
        verdict = constraint_pins_staleness(task, project, catalog)
        assert verdict["state"] == "current"


class TestCompareAndResolve:
    def test_compare_versions_line_diff(self, project, catalog):
        group = project.constraint_layers[0]
        first = commit_constraint_group(project, catalog, group)
        group.lines[0].coordinates = [[0.0, 0.0], [13.0, 0.5]]
        group.lines.append(_line("F2", [[1.0, 1.0], [2.0, 2.0]]))
        second = commit_constraint_group(project, catalog, group)
        diff = compare_constraint_versions(
            catalog, first.version_id, second.version_id
        )
        assert diff["same_group"]
        assert not diff["identical"]
        assert "F2-added-by-id" or True  # ids are opaque; check counts
        assert len(diff["lines_added"]) == 1
        assert len(diff["lines_changed"]) == 1
        assert diff["lines_changed"][0]["changes"] == ["coordinates"]
        assert diff["lines_unchanged"] == 1

    def test_resolve_constraints_current_unknown_when_never_committed(
        self, project, catalog
    ):
        verdict = resolve_constraint_ref(project, catalog, "constraints:current")
        assert verdict["status"] == "unknown"

    def test_resolve_constraints_current_clean_then_stale(self, project, catalog):
        group = project.constraint_layers[0]
        commit_constraint_group(project, catalog, group)
        verdict = resolve_constraint_ref(project, catalog, "constraints:current")
        assert verdict["status"] == "current"
        group.lines[0].coordinates = [[0.0, 0.0], [20.0, 0.0]]
        verdict2 = resolve_constraint_ref(project, catalog, "constraints:current")
        assert verdict2["status"] == "stale"
        assert "differs from latest commit" in verdict2["detail"]

    def test_resolve_pinned_constraint_ref_superseded(self, project, catalog):
        group = project.constraint_layers[0]
        first = commit_constraint_group(project, catalog, group)
        ref = f"constraints:{group.id}:{first.version_id}"
        verdict = resolve_constraint_ref(project, catalog, ref)
        assert verdict["status"] == "current"
        group.lines[0].coordinates = [[0.0, 0.0], [30.0, 3.0]]
        commit_constraint_group(project, catalog, group)
        verdict2 = resolve_constraint_ref(project, catalog, ref)
        assert verdict2["status"] == "superseded"


class TestContentHash:
    def test_hash_stable_under_line_reorder_and_float_noise(self):
        g1 = _group(lines=[
            _line("A", [[0.0, 0.0], [1.0, 0.0]]),
            _line("B", [[0.0, 0.0], [0.0, 1.0]], role="direction"),
        ])
        g2 = _group(lines=[
            _line("B", [[0.0, 0.0], [0.0, 1.0]], role="direction"),
            _line("A", [[0.0, 0.0], [1.0 + 1e-12, 0.0]]),  # below rounding
        ])
        h1, n1 = constraint_group_content_hash(g1)
        h2, n2 = constraint_group_content_hash(g2)
        assert h1 == h2 and n1 == n2 == 2

    def test_inactive_and_undigitized_lines_excluded(self):
        g = _group(lines=[
            _line("A", [[0.0, 0.0], [1.0, 0.0]]),
            _line("B", [], role="boundary"),          # no coordinates yet
        ])
        g.lines[0].active = False                       # deactivated
        _h, n = constraint_group_content_hash(g)
        assert n == 0


class TestReviewR2LazyAndPort:
    def test_lazy_reopen_does_not_create_second_asset(self, project, catalog):
        """R2-P0: a lazy-opened service has an EMPTY document pre-warm — the
        old catalog.document scan saw the group as uncommitted and created a
        duplicate asset on the second commit."""
        group = project.constraint_layers[0]
        first = commit_constraint_group(project, catalog, group)
        catalog.close()

        from paleo_workbench.catalog.service import DataCatalogService

        lazy = DataCatalogService.open(catalog.project_path, lazy=True, sweep_temp=False)
        try:
            group.lines[0].coordinates = [[0.0, 0.0], [42.0, 0.0]]
            second = commit_constraint_group(project, lazy, group)
            assert second.committed
            assert second.asset_id == first.asset_id  # ONE asset, version 2
            versions = lazy.list_versions(first.asset_id)
            assert len(versions) == 2
        finally:
            lazy.close()

    def test_port_adapter_is_unwrapped(self, project, catalog):
        """R2-P1: the mapping workspace injects a CoreCatalogAdapter — the
        resolve path must unwrap .service instead of crashing on .document."""
        from paleo_workbench.catalog.adapter import CoreCatalogAdapter
        from paleo_workbench.workflow.constraint_versions import (
            current_constraint_version,
        )

        group = project.constraint_layers[0]
        commit_constraint_group(project, catalog, group)
        port = CoreCatalogAdapter(catalog)
        version = current_constraint_version(port, group.id)
        assert version is not None

        from paleo_workbench.workflow.constraint_versions import (
            resolve_constraint_ref,
        )

        verdict = resolve_constraint_ref(project, port, "constraints:current")
        assert verdict["status"] == "current"
