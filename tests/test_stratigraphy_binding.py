"""T-SEQ-01: stratigraphy persistence and target_horizon downstream binding."""

from __future__ import annotations

from paleo_workbench.project.models import (
    FactorMapTask,
    PaleoMapDocument,
    ProjectDocument,
)
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state
from paleo_workbench.workflow.stratigraphy import (
    active_target_horizon,
    apply_stratigraphy_scheme,
    set_target_from_boundary,
)


def test_apply_stratigraphy_updates_run_and_scheme():
    project = ProjectDocument.new("Seq")
    create_compilation_run(project, "Run", "OLD", "LST/TST/HST")

    apply_stratigraphy_scheme(
        project,
        target_horizon="ZJ2",
        systems_tract_scheme="三级层序格架",
        bind_downstream=True,
    )

    assert project.stratigraphy.target_horizon == "ZJ2"
    assert project.stratigraphy.systems_tract_scheme == "三级层序格架"
    assert project.compilation_runs[-1].target_horizon == "ZJ2"
    assert project.compilation_runs[-1].sequence_scheme_ref == "三级层序格架"
    assert dashboard_state(project)["active_target_horizon"] == "ZJ2"


def test_bind_downstream_updates_matching_maps_and_factors_only():
    project = ProjectDocument.new("Bind")
    project.stratigraphy.target_horizon = "H1"
    project.paleomap_documents.extend(
        [
            PaleoMapDocument(name="A", linked_target_horizon="H1"),
            PaleoMapDocument(name="Other", linked_target_horizon="KEEP"),
            PaleoMapDocument(name="Empty", linked_target_horizon=""),
        ]
    )
    project.factor_map_tasks.extend(
        [
            FactorMapTask(
                name="H1 厚度",
                target_horizon="H1",
                factor_type="厚度",
                method="IDW",
            ),
            FactorMapTask(
                name="KEEP 砂",
                target_horizon="KEEP",
                factor_type="砂",
                method="IDW",
            ),
        ]
    )

    apply_stratigraphy_scheme(project, target_horizon="H2", bind_downstream=True)

    by_name = {d.name: d.linked_target_horizon for d in project.paleomap_documents}
    assert by_name["A"] == "H2"
    assert by_name["Empty"] == "H2"
    assert by_name["Other"] == "KEEP"
    assert project.factor_map_tasks[0].target_horizon == "H2"
    assert project.factor_map_tasks[0].name.startswith("H2")
    assert project.factor_map_tasks[1].target_horizon == "KEEP"


def test_set_target_from_boundary_appends_if_missing():
    project = ProjectDocument.new("Bound")
    project.stratigraphy.sequence_boundaries = ["SB1"]
    set_target_from_boundary(project, "SB2")
    assert project.stratigraphy.target_horizon == "SB2"
    assert "SB2" in project.stratigraphy.sequence_boundaries
    assert active_target_horizon(project) == "SB2"
