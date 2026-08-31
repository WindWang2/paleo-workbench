"""Harness execution context (P2-C).

The context is what an agent may *read* about the current session —
workspace, selection snapshot, active well/volume/map — plus the service
handles actions delegate to. Agents never mutate the context directly:
mutations happen only inside actions, through the domain services.

It is deliberately constructor-friendly for headless use (tests, batch
runs) and can be built from the live application via :meth:`from_app`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.harness.spec import DEFAULT_PERMISSIONS, ActionRisk


@dataclass(slots=True)
class SelectionSnapshot:
    """Frozen view of SelectionContext (the P1 selection bus) for agents."""

    active_well_id: str | None = None
    selected_well_ids: tuple[str, ...] = ()
    seismic_cursor: tuple[int, int, float] | None = None
    depth_range: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_well_id": self.active_well_id,
            "selected_well_ids": list(self.selected_well_ids),
            "seismic_cursor": list(self.seismic_cursor) if self.seismic_cursor else None,
            "depth_range": list(self.depth_range) if self.depth_range else None,
        }


@dataclass(slots=True)
class ActionContext:
    """Everything an action may touch. Services are passed in; the harness
    never reaches into UI private state or opens databases by itself."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace_id: str | None = None
    project_path: str | None = None
    # --- services (single authorities; injected, never re-created) --------
    catalog: Any | None = None        # CatalogPort (CoreCatalogAdapter in-app)
    project: Any | None = None        # live ProjectDocument (GUI-owned; READ for agents)
    # --- context awareness ------------------------------------------------
    selection: SelectionSnapshot = field(default_factory=SelectionSnapshot)
    active_survey_id: str | None = None
    active_well_id: str | None = None
    active_volume: Any | None = None  # SeismicVolumeRef
    current_map_id: str | None = None
    # --- in-process handles actions may stash results into ----------------
    map_documents: dict[str, Any] = field(default_factory=dict)   # id -> MapDocument
    well_logs: dict[str, Any] = field(default_factory=dict)       # well_id -> WellLogData
    well_displays: dict[str, Any] = field(default_factory=dict)   # well_id -> display doc
    factor_datasets: dict[str, Any] = field(default_factory=dict) # factor_name -> dataset
    compositions: dict[str, Any] = field(default_factory=dict)    # map_id -> MapCompositionDocument
    # --- governance / control ---------------------------------------------
    permissions: frozenset = DEFAULT_PERMISSIONS
    progress: Any | None = None       # callable(ratio, message) or token-aware object
    cancel: Any | None = None         # token with is_cancelled/raise_if_cancelled
    extras: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ checks --
    def has(self, attr: str) -> bool:
        return getattr(self, attr, None) is not None

    def require(self, attr: str) -> Any:
        value = getattr(self, attr, None)
        if value is None:
            raise LookupError(
                f"action context is missing {attr!r} (open the relevant workspace/"
                "survey/map first, or pass it explicitly)"
            )
        return value

    def permits(self, risk: ActionRisk) -> bool:
        return risk in self.permissions

    def snapshot_description(self) -> dict[str, Any]:
        """Machine-readable summary for agent prompts (read-only facts)."""
        return {
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "project_path": self.project_path,
            "selection": self.selection.to_dict(),
            "active_survey_id": self.active_survey_id,
            "active_well_id": self.active_well_id,
            "active_volume": getattr(self.active_volume, "to_dict", lambda: None)(),
            "current_map_id": self.current_map_id,
            "open_map_documents": sorted(self.map_documents),
            "loaded_wells": sorted(self.well_logs),
            "available_factor_datasets": sorted(self.factor_datasets),
        }

    # -------------------------------------------------------------- build --
    @classmethod
    def from_app(cls, window: Any, **overrides: Any) -> "ActionContext":
        """Build a context from the live application window (read-only view).

        Pulls from the P1 coordination singletons (SelectionContext via the
        window's public selection surface, catalog adapter, project
        document) and grants WRITE — an app session sits behind the UI and
        WRITE actions still go through domain services with provenance.
        Headless/programmatic contexts start with READ+COMPUTE only.
        """
        context = cls(permissions=frozenset({ActionRisk.READ, ActionRisk.COMPUTE, ActionRisk.WRITE}))
        controller = getattr(window, "project_controller", None)
        project = getattr(controller, "project", None) if controller is not None else None
        if project is not None:
            context.project = project
            meta = getattr(project, "meta", None)
            context.workspace_id = getattr(meta, "name", None)
            path = getattr(controller, "current_project_path", None) if controller else None
            context.project_path = str(path) if path else None
        catalog = None
        try:
            from paleo_workbench.catalog.runtime import get_catalog

            catalog = get_catalog()
        except Exception:
            catalog = None
        context.catalog = catalog
        try:
            # Public surface first (property on the window), shell fallback.
            selection_context = getattr(window, "selection_context", None)
            if selection_context is None:
                shell = getattr(window, "shell", None) or getattr(window, "_shell", None)
                selection_context = getattr(shell, "selection_context", None)
            if selection_context is not None:
                state = selection_context.snapshot()
                context.selection = SelectionSnapshot(
                    active_well_id=state.active_well_id,
                    selected_well_ids=tuple(state.selected_well_ids or ()),
                    seismic_cursor=tuple(state.seismic_cursor) if state.seismic_cursor else None,
                    depth_range=tuple(state.depth_range) if state.depth_range else None,
                )
                context.active_well_id = state.active_well_id
        except Exception:
            pass
        for key, value in overrides.items():
            setattr(context, key, value)
        return context
