"""Deterministic current-project version selection (Stage 9).

Freshness is *derived* from:

* catalog asset ``current_version_id`` pointers
* project-side interpretation / product refs
* optional explicit overrides (tests)

Never stamps ``stale=True`` on immutable historical DataVersions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from paleo_workbench.catalog.runtime import get_catalog, get_catalog_service


@dataclass
class CurrentProjectVersionContext:
    """Selected scientific versions for the open project.

    ``current_by_asset``: asset_id → currently selected version_id
    ``selected_version_ids``: flat set of all currently selected version ids
    ``expected_identity``: optional run-identity expectations keyed by
        domain_task_id or run_id (generator / snapshot / parameters)
    """

    current_by_asset: dict[str, str] = field(default_factory=dict)
    selected_version_ids: set[str] = field(default_factory=set)
    # Optional: version_id → kind/name for UI
    labels: dict[str, str] = field(default_factory=dict)
    # domain_task_id or operation key → expected computation identity
    expected_identity: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Display-only params that must NEVER invalidate scientific freshness
    display_only_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "colormap",
                "color_map",
                "line_width",
                "linewidth",
                "viewport",
                "visibility",
                "opacity",
                "color",
                "display",
                "style",
                "zoom",
                "pan",
            }
        )
    )
    # domain_task_id → currently selected product version_id (project pointer)
    current_by_domain_task: dict[str, str] = field(default_factory=dict)

    def select(self, asset_id: str, version_id: str, *, label: str = "") -> None:
        """Record that *asset_id* currently points at *version_id*.

        Replacing the selection for an asset removes the previous version id
        from ``selected_version_ids`` so historical tips do not stay "current".
        """
        if not asset_id or not version_id:
            return
        prev = self.current_by_asset.get(asset_id)
        if prev and prev != version_id:
            self.selected_version_ids.discard(prev)
        self.current_by_asset[asset_id] = version_id
        self.selected_version_ids.add(version_id)
        if label:
            self.labels[version_id] = label

    def mark_domain_product_current(self, domain_task_id: str, version_id: str) -> None:
        """Record which product version is current for a domain task.

        Historical recompute outputs (often new assets) remain in the catalog but
        are not the project-selected tip.
        """
        if not domain_task_id or not version_id:
            return
        prev = self.current_by_domain_task.get(domain_task_id)
        if prev and prev != version_id:
            self.selected_version_ids.discard(prev)
        self.current_by_domain_task[domain_task_id] = version_id
        self.selected_version_ids.add(version_id)

    def current_for_asset(self, asset_id: str | None) -> str | None:
        if not asset_id:
            return None
        return self.current_by_asset.get(asset_id)

    def is_current_version(self, version_id: str) -> bool:
        return version_id in self.selected_version_ids

    def set_expected_identity(
        self,
        key: str,
        *,
        generator_version: str | None = None,
        input_snapshot_hash: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        model_ref: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if generator_version is not None:
            payload["generator_version"] = generator_version
        if input_snapshot_hash is not None:
            payload["input_snapshot_hash"] = input_snapshot_hash
        if parameters is not None:
            # Strip display-only keys so style changes do not stale science.
            payload["parameters"] = {
                k: v
                for k, v in dict(parameters).items()
                if k not in self.display_only_keys and not str(k).startswith("_display")
            }
        if model_ref is not None:
            payload["model_ref"] = dict(model_ref)
        self.expected_identity[key] = payload


def resolve_current_project_version_context(
    project: Any | None = None,
    *,
    catalog: Any | None = None,
    service: Any | None = None,
    extra_selected: Mapping[str, str] | None = None,
) -> CurrentProjectVersionContext:
    """Build a deterministic current-version context for the open project.

    Resolution order (later wins for the same asset):

    1. Catalog asset ``current_version_id`` (via DataCatalogService when present)
    2. Project ``horizon_interpretations[].current_version_id``
    3. Factor task ``grid_artifact_version_id`` (current product pointer)
    4. Explicit *extra_selected* asset_id → version_id overrides
    """
    ctx = CurrentProjectVersionContext()
    cat = catalog if catalog is not None else get_catalog()
    svc = service if service is not None else get_catalog_service()

    # 1. Catalog current pointers
    if svc is not None:
        try:
            assets = svc.list_assets(include_trashed=False)
        except TypeError:
            assets = svc.list_assets()
        for asset in assets:
            cur = getattr(asset, "current_version_id", None)
            if cur:
                ctx.select(asset.id, cur, label=getattr(asset, "name", "") or "")

    # If only CatalogPort is available, infer "current" as the last version per asset
    # when no service is present (tests / degraded mode). Prefer explicit select later.
    if svc is None and cat is not None:
        by_asset: dict[str, list[Any]] = {}
        for ver in cat.list_versions():
            by_asset.setdefault(ver.asset_id, []).append(ver)
        for asset_id, vers in by_asset.items():
            if asset_id in ctx.current_by_asset:
                continue
            # Stable: last by created_at then version_id
            vers_sorted = sorted(
                vers, key=lambda v: (getattr(v, "created_at", "") or "", v.version_id)
            )
            last = vers_sorted[-1]
            ctx.select(asset_id, last.version_id, label=getattr(last, "name", "") or "")

    if project is None:
        if extra_selected:
            for asset_id, vid in extra_selected.items():
                ctx.select(asset_id, vid)
        return ctx

    # 2. Horizon interpretation refs (project selection may differ from last catalog write)
    for ref in getattr(project, "horizon_interpretations", None) or []:
        vid = getattr(ref, "current_version_id", None)
        if not vid or cat is None:
            continue
        ver = cat.resolve_version(vid)
        if ver is not None:
            ctx.select(ver.asset_id, vid, label=getattr(ref, "name", "") or "")
        else:
            # Unknown to catalog — still treat as selected version id
            ctx.selected_version_ids.add(vid)
            ctx.labels[vid] = getattr(ref, "name", "") or vid

        # Expected identity for the interpretation itself
        fp = getattr(ref, "scientific_fingerprint", "") or ""
        if fp:
            # Key must match DataRun.domain_task_id (interpretation_id).
            ctx.set_expected_identity(
                str(getattr(ref, "id", "") or vid),
                input_snapshot_hash=fp,
                generator_version="horizon-interp-v1",
            )

    # 2b. Multi-well correlation interpretation current versions (Stage 12)
    for ref in getattr(project, "correlation_interpretations", None) or []:
        vid = getattr(ref, "current_version_id", None)
        if not vid:
            continue
        if cat is not None:
            ver = cat.resolve_version(vid)
            if ver is not None:
                ctx.select(ver.asset_id, vid, label=getattr(ref, "name", "") or "")
                ctx.mark_domain_product_current(
                    str(getattr(ref, "id", "") or ""), vid
                )
                _deselect_superseded_domain_tips(
                    ctx, cat, str(getattr(ref, "id", "") or ""), vid
                )
            else:
                ctx.selected_version_ids.add(vid)
                ctx.labels[vid] = getattr(ref, "name", "") or vid
        else:
            ctx.selected_version_ids.add(vid)
        fp = getattr(ref, "scientific_fingerprint", "") or ""
        if fp:
            ctx.set_expected_identity(
                str(getattr(ref, "id", "") or vid),
                input_snapshot_hash=fp,
                generator_version="strat-corr-v1",
            )

    # 2c. Fault interpretation current versions
    for ref in getattr(project, "fault_interpretations", None) or []:
        vid = getattr(ref, "current_version_id", None)
        if not vid:
            continue
        if cat is not None:
            ver = cat.resolve_version(vid)
            if ver is not None:
                ctx.select(ver.asset_id, vid, label=getattr(ref, "name", "") or "")
                ctx.mark_domain_product_current(
                    str(getattr(ref, "id", "") or ""), vid
                )
                _deselect_superseded_domain_tips(
                    ctx, cat, str(getattr(ref, "id", "") or ""), vid
                )
            else:
                ctx.selected_version_ids.add(vid)
                ctx.labels[vid] = getattr(ref, "name", "") or vid
        else:
            ctx.selected_version_ids.add(vid)
        fp = getattr(ref, "scientific_fingerprint", "") or ""
        if fp:
            ctx.set_expected_identity(
                str(getattr(ref, "id", "") or vid),
                input_snapshot_hash=fp,
                generator_version="fault-interp-v1",
            )

    # 3. Factor map product pointers + expected scientific identity.
    # Project pointer is the authoritative "current" product; other historical
    # factor assets must not remain selected (adapter creates one asset per run).
    for task in getattr(project, "factor_map_tasks", None) or []:
        grid_vid = getattr(task, "grid_artifact_version_id", None)
        if grid_vid and cat is not None:
            ver = cat.resolve_version(grid_vid)
            if ver is not None:
                ctx.select(
                    ver.asset_id,
                    grid_vid,
                    label=getattr(task, "name", "") or "",
                )
                ctx.mark_domain_product_current(
                    str(getattr(task, "id", "") or ""),
                    grid_vid,
                )
                # Superseded per-run asset tips (legacy asset-per-run catalogs)
                # must not stay selected and poison rule 3 (issue #373 / C15).
                _deselect_superseded_domain_tips(
                    ctx,
                    cat,
                    str(getattr(task, "id", "") or ""),
                    grid_vid,
                )
        snap = getattr(task, "input_snapshot_hash", "") or ""
        gen = getattr(task, "generator_version", None)
        params = dict(getattr(task, "parameters", None) or {})
        # Scientific params only (method/power/radius etc.); display stripped later
        sci_params = {
            "factor_type": getattr(task, "factor_type", None),
            "target_horizon": getattr(task, "target_horizon", None),
            "method": getattr(task, "method", None),
        }
        # Include known scientific keys from parameters if present
        for key in (
            "power",
            "search_radius",
            "grid_n",
            "backend",
            "anisotropy",
            "result_fingerprint",
            "algorithm_fingerprint",
        ):
            if key in params:
                sci_params[key] = params[key]
        ctx.set_expected_identity(
            getattr(task, "id", "") or f"factor:{getattr(task, 'name', '')}",
            generator_version=gen,
            input_snapshot_hash=snap or None,
            parameters=sci_params,
        )

    # 4. Prediction tasks
    for task in getattr(project, "prediction_tasks", None) or []:
        snap = getattr(task, "input_snapshot_hash", "") or ""
        gen = getattr(task, "generator_version", None)
        model_meta = dict(getattr(task, "model_metadata", None) or {})
        model_ref = None
        if model_meta:
            model_ref = {
                k: model_meta[k]
                for k in (
                    "model_id",
                    "model_version",
                    "model_version_id",
                    "preprocessing_version",
                )
                if k in model_meta
            } or model_meta
        sci_params = {
            "adapter_kind": getattr(task, "adapter_kind", None),
            "threshold": (getattr(task, "parameters", None) or {}).get("threshold")
            if hasattr(task, "parameters")
            else model_meta.get("threshold"),
        }
        ctx.set_expected_identity(
            getattr(task, "id", "") or f"pred:{getattr(task, 'name', '')}",
            generator_version=gen,
            input_snapshot_hash=snap or None,
            parameters={k: v for k, v in sci_params.items() if v is not None},
            model_ref=model_ref,
        )

    # 5. Explicit overrides
        if extra_selected:
            for asset_id, vid in extra_selected.items():
                ctx.select(asset_id, vid)

    return ctx


def _deselect_superseded_domain_tips(
    ctx: CurrentProjectVersionContext,
    catalog: Any | None,
    domain_task_id: str,
    keep_version_id: str,
) -> None:
    """Keep only the project-selected tip of a domain task selected.

    Legacy asset-per-run catalogs leave superseded per-run asset tips selected
    through their catalog ``current_version_id``; those tips must not keep
    poisoning freshness rule 3 with a competing "current" version (issue
    #373 / C15). Explicit selections applied later (``extra_selected``)
    still win. Best-effort: a catalog that cannot resolve versions simply
    leaves the selection untouched.
    """
    if catalog is None or not domain_task_id or not keep_version_id:
        return
    try:
        run_by_id = {r.run_id: r for r in catalog.list_runs()}
    except Exception:
        return
    for vid in list(ctx.selected_version_ids):
        if vid == keep_version_id:
            continue
        try:
            ver = catalog.resolve_version(vid)
        except Exception:
            continue
        if ver is None or not getattr(ver, "producing_run_id", None):
            continue
        producing = run_by_id.get(ver.producing_run_id)
        if producing is None:
            continue
        if getattr(producing, "domain_task_id", None) == domain_task_id:
            ctx.selected_version_ids.discard(vid)
