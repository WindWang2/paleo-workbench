"""Stratigraphic framework persistence and target_horizon downstream binding.

Sequence page is the editor; preparation / mapping / compilation runs consume
``ProjectDocument.stratigraphy.target_horizon`` (and linked map horizons).
"""

from __future__ import annotations

from paleo_workbench.project.models import ProjectDocument, StratigraphicFramework


def apply_stratigraphy_scheme(
    project: ProjectDocument,
    *,
    target_horizon: str | None = None,
    systems_tract_scheme: str | None = None,
    interpretation_version: str | None = None,
    sequence_boundaries: list[str] | None = None,
    bind_downstream: bool = True,
) -> StratigraphicFramework:
    """Write stratigraphy fields and optionally sync run / maps / factor tasks.

    When ``target_horizon`` changes and ``bind_downstream`` is True:
    - active ``CompilationRun.target_horizon`` / ``sequence_scheme_ref`` update
    - ``PaleoMapDocument.linked_target_horizon`` updated when empty or equal to
      the previous target (does not clobber unrelated horizons)
    - ``FactorMapTask.target_horizon`` same rule
    """
    strat = project.stratigraphy
    previous_horizon = (strat.target_horizon or "").strip()

    if target_horizon is not None:
        strat.target_horizon = str(target_horizon).strip()
    if systems_tract_scheme is not None:
        strat.systems_tract_scheme = str(systems_tract_scheme).strip() or strat.systems_tract_scheme
    if interpretation_version is not None:
        strat.interpretation_version = str(interpretation_version).strip() or strat.interpretation_version
    if sequence_boundaries is not None:
        strat.sequence_boundaries = [
            str(b).strip() for b in sequence_boundaries if str(b).strip()
        ]

    new_horizon = (strat.target_horizon or "").strip()
    scheme = strat.systems_tract_scheme or ""

    if project.compilation_runs:
        run = project.compilation_runs[-1]
        if new_horizon:
            run.target_horizon = new_horizon
        if scheme:
            run.sequence_scheme_ref = scheme

    if bind_downstream and new_horizon:
        _bind_target_horizon(project, new_horizon, previous=previous_horizon)

    return strat


def _bind_target_horizon(
    project: ProjectDocument,
    new_horizon: str,
    *,
    previous: str,
) -> None:
    """Propagate target horizon to maps/factors that share the previous value."""
    for doc in project.paleomap_documents:
        linked = (doc.linked_target_horizon or "").strip()
        if linked in ("", previous) or (previous and linked == previous):
            doc.linked_target_horizon = new_horizon

    for task in project.factor_map_tasks:
        current = (task.target_horizon or "").strip()
        if current in ("", previous) or (previous and current == previous):
            task.target_horizon = new_horizon
            # Keep display name aligned when it was horizon-prefixed.
            if task.name.startswith(f"{previous} ") if previous else False:
                task.name = f"{new_horizon} {task.factor_type or task.name[len(previous) + 1:]}"
            elif not previous and task.factor_type and task.name == task.factor_type:
                task.name = f"{new_horizon} {task.factor_type}"


def set_target_from_boundary(
    project: ProjectDocument,
    boundary: str,
    *,
    bind_downstream: bool = True,
) -> StratigraphicFramework:
    """Select a sequence boundary as the active target horizon."""
    name = str(boundary or "").strip()
    if not name:
        return project.stratigraphy
    if name not in project.stratigraphy.sequence_boundaries:
        project.stratigraphy.sequence_boundaries.append(name)
    return apply_stratigraphy_scheme(
        project,
        target_horizon=name,
        bind_downstream=bind_downstream,
    )


def active_target_horizon(project: ProjectDocument) -> str:
    """Single source of truth for the active mapping/prep horizon label."""
    if project.compilation_runs:
        th = (project.compilation_runs[-1].target_horizon or "").strip()
        if th:
            return th
    return (project.stratigraphy.target_horizon or "").strip()
