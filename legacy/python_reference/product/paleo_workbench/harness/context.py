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


@dataclass(slots=True, frozen=True)
class SelectionSnapshot:
    """Frozen view of SelectionContext (the P1 selection bus) for agents.

    Immutable by contract: the host re-snapshots when the session state
    changes; actions and workflows capture the snapshot they started with
    (an execution never sees a silently mutated selection).
    """

    active_well_id: str | None = None
    selected_well_ids: tuple[str, ...] = ()
    seismic_cursor: tuple[int, int, float] | None = None
    depth_range: tuple[float, float] | None = None
    # --- Harness 2.0 snapshot fields ---------------------------------------
    target_horizon: str | None = None          # active horizon id
    active_fault_id: str | None = None
    active_interpretation_id: str | None = None
    active_layer_id: str | None = None         # active map layer
    selected_layer_id: str | None = None       # V11: tree-highlighted layer
    selected_asset_id: str | None = None       # V11: data asset under focus
    map_extent: tuple[float, float, float, float] | None = None
    map_crs: str | None = None                 # declared CRS of the map context
    selected_feature_refs: tuple[str, ...] = ()  # feature identities, not geometries
    active_version_id: str | None = None       # active catalog data version
    spatial_cursor: tuple[float, float] | None = None
    depth_cursor: tuple[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_well_id": self.active_well_id,
            "selected_well_ids": list(self.selected_well_ids),
            "seismic_cursor": list(self.seismic_cursor) if self.seismic_cursor else None,
            "depth_range": list(self.depth_range) if self.depth_range else None,
            "target_horizon": self.target_horizon,
            "active_fault_id": self.active_fault_id,
            "active_interpretation_id": self.active_interpretation_id,
            "active_layer_id": self.active_layer_id,
            "selected_layer_id": self.selected_layer_id,
            "selected_asset_id": self.selected_asset_id,
            "map_extent": list(self.map_extent) if self.map_extent else None,
            "map_crs": self.map_crs,
            "selected_feature_refs": list(self.selected_feature_refs),
            "active_version_id": self.active_version_id,
            "spatial_cursor": list(self.spatial_cursor) if self.spatial_cursor else None,
            "depth_cursor": list(self.depth_cursor) if self.depth_cursor else None,
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

    def derived(self, **overrides: Any) -> "ActionContext":
        """A per-execution copy sharing services and stashes but with its
        own ``extras`` (minus volatile executor keys).

        The workflow engine derives one context per node so parallel nodes
        never race on the admission-lease slot; ``admission_lease`` is
        deliberately not copied — each action's executor sets its own.
        """
        clone = ActionContext(
            session_id=self.session_id,
            workspace_id=self.workspace_id,
            project_path=self.project_path,
            catalog=self.catalog,
            project=self.project,
            selection=self.selection,
            active_survey_id=self.active_survey_id,
            active_well_id=self.active_well_id,
            active_volume=self.active_volume,
            current_map_id=self.current_map_id,
            permissions=self.permissions,
            progress=self.progress,
            extras={
                k: v
                for k, v in self.extras.items()
                if k != "admission_lease"
            },
        )
        # Shared in-process stashes are cooperative workflow state: nodes of
        # one run legitimately exchange handles through them.
        clone.map_documents = self.map_documents
        clone.well_logs = self.well_logs
        clone.well_displays = self.well_displays
        clone.factor_datasets = self.factor_datasets
        clone.compositions = self.compositions
        for key, value in overrides.items():
            setattr(clone, key, value)
        return clone

    def provider_context(self, **overrides: Any) -> Any:
        """Build the :class:`ProviderContext` for a nested provider execution.

        The single sanctioned way for handlers to construct a provider
        context: it forwards the session's services, progress, cancellation,
        workspace containment root — and, while the executor runs this
        action, the enclosing governor admission lease so the nested
        execution inherits the reservation instead of double-admitting the
        same work against the streaming-buffer budget.
        """
        from pathlib import Path

        from paleo_workbench.providers.base import ProviderContext

        workspace_root = overrides.pop(
            "workspace_root",
            str(Path(self.project_path).parent)
            if self.project_path
            else str(Path.cwd()),
        )
        provider_context = ProviderContext(
            catalog=overrides.pop("catalog", self.catalog),
            workspace_root=workspace_root,
            emit_progress=overrides.pop("emit_progress", self.progress),
            cancel=overrides.pop("cancel", self.cancel),
            work_dir=overrides.pop("work_dir", self.extras.get("work_dir")),
        )
        lease = self.extras.get("admission_lease")
        if lease is not None:
            provider_context.extras["admission_lease"] = lease
        provider_context.extras.update(overrides)
        return provider_context

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
            "current_workflow_run_id": self.extras.get("workflow_run_id"),
        }

    # -------------------------------------------------------------- build --
    @classmethod
    def from_app(cls, window: Any, **overrides: Any) -> "ActionContext":
        """Build a context from the live application window (read-only view).

        Pulls from the P1 coordination singletons (SelectionContext via the
        window's public selection surface, catalog adapter, project
        document). Default permissions are READ+COMPUTE (#1186): WRITE-risk
        actions (map export/factor-map, derived seismic stores) require an
        explicit grant — pass ``permissions=DEFAULT_PERMISSIONS |
        {ActionRisk.WRITE}`` for a session that should be allowed to write.
        """
        context = cls(permissions=DEFAULT_PERMISSIONS)
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
                    target_horizon=getattr(state, "active_horizon_id", None),
                    active_fault_id=getattr(state, "active_fault_id", None),
                    active_interpretation_id=getattr(state, "active_interpretation_id", None),
                    # V11：active（编辑控制器权威）优先，回落 selected（树点选）。
                    active_layer_id=(
                        getattr(state, "active_layer_id", None)
                        or getattr(state, "selected_layer_id", None)
                    ),
                    selected_layer_id=getattr(state, "selected_layer_id", None),
                    selected_asset_id=getattr(state, "selected_asset_id", None),
                    map_extent=tuple(state.map_extent)
                    if getattr(state, "map_extent", None)
                    else None,
                    map_crs=getattr(state, "map_crs", None),
                    selected_feature_refs=tuple(
                        getattr(state, "selected_feature_ids", None) or ()
                    ),
                    spatial_cursor=tuple(state.spatial_cursor)
                    if getattr(state, "spatial_cursor", None)
                    else None,
                    depth_cursor=tuple(state.depth_cursor)
                    if getattr(state, "depth_cursor", None)
                    else None,
                )
                context.active_well_id = state.active_well_id
        except Exception:
            pass
        for key, value in overrides.items():
            setattr(context, key, value)
        return context
