"""Cartographic QA rules (V7 §14).

Rule set for the *cartographic* chain — CRS/unit discipline, geometry
validity, extent coverage, staleness, source presence, renderer↔domain
agreement, legend/furniture completeness, prediction confidence, degraded
rendering paths, export-bound maturity, style bindings, scalar ranges and
factor-group integrity. Every issue is built by
:func:`paleo_workbench.workflow.qc.make_issue` and localizes the problem
(``layer_id`` / ``feature_id`` / ``ref`` / ``geometry``) — QA answers "what
is wrong and where", never just a score.

Honest degradation is mandatory: a rule whose inputs are missing (no
snapshot, no catalog, unknown layer role, absent symbols library …) is
*skipped with a note* in the summary — never guessed, never silently
dropped. :func:`collect_cartographic_qa` returns the issues together with
``{rule_id: {"evaluated": n, "skipped": n, "notes": [...]}}``;
:func:`collect_cartographic_qa_issues` returns the bare issue list for
drop-in use beside :func:`workflow.map_qa_rules.collect_extended_qc_issues`.

WIRING GAP (deliberate, documented): the stage QA action
(``ui/workstation/stage_actions.py`` ``run_qa``) is owned by the main agent
and is NOT edited from here. Stage QA can already include this collector by
calling both — ``collect_extended_qc_issues(...)`` +
``collect_cartographic_qa_issues(...)`` — and
``workflow.map_qa_rules.cartographic_issues`` is the thin delegate kept in
the QA module family so the call site stays one import.
``tests/test_cartographic_qa.py::test_stage_qa_can_compose_both_collectors``
proves the composition works; closing the gap at the call site is a main-
agent one-liner.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from paleo_workbench.mapping_workspace.layer_groups import (
    FACTOR_CHILD_ORDER,
    factor_task_of_group,
    is_factor_group,
)
from paleo_workbench.mapping_workspace.stage_state import (
    MATURITY_ORDER,
    ArtifactMaturity,
    MappingWorkspaceState,
)
from paleo_workbench.workflow.crs_policy import crs_is_geographic
from paleo_workbench.workflow.qc import make_issue

logger = logging.getLogger(__name__)

__all__ = [
    "CARTOGRAPHIC_QA_RULES",
    "cartographic_rule_summary",
    "collect_cartographic_qa",
    "collect_cartographic_qa_issues",
]

CARTOGRAPHIC_QA_RULES: list[str] = [
    "crs_invalid",
    "unit_unknown",
    "geometry_invalid",
    "layer_outside_extent",
    "stale_input",
    "missing_source",
    "renderer_domain_mismatch",
    "legend_empty",
    "core_furniture_missing",
    "low_confidence",
    "fallback_renderer",
    "unpublished_data_in_export",
    "style_binding_unknown",
    "raster_range_invalid",
    "broken_factor_group",
]

DEFAULT_CONFIDENCE_THRESHOLD = 0.5

_MATURITY_EXPORT_FLOOR = ArtifactMaturity.REVIEWED

# Composition element types whose emptiness is a legend problem (§14
# "empty legend"): any legend-family element with nothing to show.
_LEGEND_FAMILY_VALUES = frozenset({
    "legend", "facies_legend", "well_legend", "lithology_legend",
})

# Core furniture a template-built page promises (§14; the composer registry
# declares all of these as basic components — a template composition that
# lacks one has a gap, not a style choice).
_CORE_FURNITURE_VALUES = ("main_map", "scale_bar", "north_arrow", "title")


# ---------------------------------------------------------------------------
# Plumbing: per-rule accounting + honest skip notes
# ---------------------------------------------------------------------------


class _RuleStats:
    """evaluated / skipped counters + skip notes per rule id."""

    def __init__(self) -> None:
        self.evaluated: dict[str, int] = {}
        self.skipped: dict[str, int] = {}
        self.notes: dict[str, list[str]] = {}

    def count(self, rule: str, n: int = 1) -> None:
        self.evaluated[rule] = self.evaluated.get(rule, 0) + n

    def skip(self, rule: str, note: str, n: int = 1) -> None:
        self.skipped[rule] = self.skipped.get(rule, 0) + n
        self.notes.setdefault(rule, []).append(note)

    def summary(self) -> dict[str, dict[str, Any]]:
        return {
            rule: {
                "evaluated": self.evaluated.get(rule, 0),
                "skipped": self.skipped.get(rule, 0),
                "notes": list(self.notes.get(rule, ())),
            }
            for rule in CARTOGRAPHIC_QA_RULES
        }


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _snapshot_layers(snapshot: Any) -> list[Any]:
    if snapshot is None:
        return []
    layers = getattr(snapshot, "layers", None)
    if layers is None and isinstance(snapshot, (list, tuple)):
        layers = snapshot
    return [layer for layer in (layers or ())]


def _workspace_state(project: Any) -> MappingWorkspaceState | None:
    raw = getattr(project, "mapping_workspace", None)
    if not raw:
        return None
    try:
        return MappingWorkspaceState.from_dict(dict(raw))
    except Exception:  # noqa: BLE001 — a corrupt state must not kill QA
        logger.warning("mapping_workspace state unparsable; role rules skip",
                       exc_info=True)
        return None


def _compositions(project: Any) -> list[Any]:
    return list(getattr(project, "compositions", None) or ())


def _pyproj_available() -> bool:
    try:
        import pyproj  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _crs_issues(project: Any, snapshot: Any, stats: _RuleStats) -> list[dict]:
    """Invalid CRS strings, and CRS whose axis units cannot be determined.

    Reuses :func:`workflow.crs_policy.crs_is_geographic` as the single
    predicate (True/False = axes known, ``None`` = unknown). A declared CRS
    that pyproj rejects outright is ``crs_invalid`` (error); a declared CRS
    whose units cannot be verified (unrecognized id without pyproj) is
    ``unit_unknown`` (warning) — an unverifiable unit silently corrupts
    scale bars and distance labels. Undeclared CRS is the EXISTING
    ``crs_undeclared`` rule (workflow.map_qa_rules) and is not duplicated.
    """
    issues: list[dict] = []
    have_pyproj = _pyproj_available()
    checked: list[tuple[str, str]] = []  # (layer_id, crs)
    for layer in getattr(project, "user_vector_layers", None) or []:
        checked.append((str(_field(layer, "id", "")), str(_field(layer, "crs", "") or "")))
    for layer in _snapshot_layers(snapshot):
        checked.append((str(_field(layer, "id", "")), str(_field(layer, "crs", "") or "")))
    if not checked:
        stats.skip("crs_invalid", "no layers to check (project/snapshot empty)")
        stats.skip("unit_unknown", "no layers to check (project/snapshot empty)")
        return issues

    for layer_id, crs in checked:
        if not crs:
            stats.skip(
                "crs_invalid",
                "undeclared CRS — the domain of the existing "
                "crs_undeclared rule (workflow.map_qa_rules)",
            )
            stats.skip(
                "unit_unknown",
                "undeclared CRS — the domain of the existing "
                "crs_undeclared rule (workflow.map_qa_rules)",
            )
            continue
        stats.count("crs_invalid")
        stats.count("unit_unknown")
        if have_pyproj:
            try:
                from pyproj import CRS

                CRS.from_user_input(crs)
                continue  # resolvable → units decidable, nothing to report
            except Exception:
                issues.append(
                    make_issue(
                        rule="crs_invalid",
                        severity="error",
                        message=f"图层 {layer_id} 的 CRS {crs!r} 无法解析（无效标识）",
                        feature_kind="layer",
                        ref=layer_id,
                        extra={"layer_id": layer_id, "crs": crs},
                    )
                )
                continue
        if crs_is_geographic(crs) is None:
            issues.append(
                make_issue(
                    rule="unit_unknown",
                    severity="warning",
                    message=(
                        f"图层 {layer_id} 的 CRS {crs!r} 轴单位无法验证"
                        "（无 pyproj 且非内置已知系）——比例尺/距离标注不可信"
                    ),
                    feature_kind="layer",
                    ref=layer_id,
                    extra={"layer_id": layer_id, "crs": crs},
                )
            )
    return issues


def _geometry_issues(project: Any, stats: _RuleStats) -> list[dict]:
    """Per-feature validity via the bridge-first facade (§4)."""
    from paleo_workbench.mapping import geometry_operations

    issues: list[dict] = []
    engine_ok = True
    layers = list(getattr(project, "user_vector_layers", None) or [])
    if not layers:
        stats.skip("geometry_invalid", "no user vector layers to validate")
        return issues
    for layer in layers:
        layer_id = str(_field(layer, "id", ""))
        for feature in _field(layer, "features", None) or []:
            geometry = _field(feature, "geometry", None) or {}
            if not geometry or not _field(geometry, "type", ""):
                stats.skip("geometry_invalid", "feature without geometry", 1)
                continue
            if not engine_ok:
                stats.skip(
                    "geometry_invalid",
                    "no validation engine (qgis bridge + shapely both absent)",
                    1,
                )
                continue
            stats.count("geometry_invalid")
            try:
                result = geometry_operations.validate(dict(geometry))
            except RuntimeError:
                engine_ok = False
                stats.skip(
                    "geometry_invalid",
                    "no validation engine (qgis bridge + shapely both absent)",
                    1,
                )
                continue
            if not result.valid:
                issues.append(
                    make_issue(
                        rule="geometry_invalid",
                        severity="error",
                        message=(
                            f"图层 {layer_id} 要素 "
                            f"{_field(feature, 'id', '')} 几何无效："
                            f"{result.reason or 'invalid'}（{result.engine}）"
                        ),
                        feature_id=str(_field(feature, "id", "") or ""),
                        feature_kind="layer",
                        ref=layer_id,
                        geometry=dict(geometry),
                        extra={
                            "layer_id": layer_id,
                            "engine": result.engine,
                            "reason": result.reason,
                        },
                    )
                )
    return issues


def _layer_bbox(layer: Any) -> tuple[float, float, float, float] | None:
    coords: list[tuple[float, float]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if (
                len(node) >= 2
                and isinstance(node[0], (int, float))
                and isinstance(node[1], (int, float))
            ):
                coords.append((float(node[0]), float(node[1])))
                return
            for item in node:
                _walk(item)

    for feature in _field(layer, "features", None) or ():
        geometry = _field(feature, "geometry", None) or {}
        node = geometry.get("coordinates") if isinstance(geometry, Mapping) else geometry
        _walk(node)
    if coords:
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        return (min(xs), min(ys), max(xs), max(ys))
    extent = _field(layer, "extent", None)
    if extent and len(extent) == 4:
        x0, y0, x1, y1 = (float(v) for v in extent)
        if (x0, y0, x1, y1) != (0.0, 0.0, 1.0, 1.0):  # placeholder extent
            return (x0, y0, x1, y1)
    return None


def _outside_extent_issues(
    project: Any, snapshot: Any, stats: _RuleStats
) -> list[dict]:
    """Layers fully outside the workarea/map extent (disjoint bboxes)."""
    issues: list[dict] = []
    workarea = getattr(project, "workarea", None)
    boundary = list(_field(workarea, "boundary", None) or []) if workarea else []
    if not boundary:
        stats.skip(
            "layer_outside_extent",
            "no workarea boundary on the project — nothing to compare against",
        )
        return issues
    xs = [float(p[0]) for p in boundary if len(p) >= 2]
    ys = [float(p[1]) for p in boundary if len(p) >= 2]
    if not xs or not ys:
        stats.skip("layer_outside_extent", "workarea boundary has no coordinates")
        return issues
    ref_box = (min(xs), min(ys), max(xs), max(ys))
    project_crs = str(_field(workarea, "project_crs", "") or "")

    def _check(layer: Any) -> None:
        layer_id = str(_field(layer, "id", ""))
        bbox = _layer_bbox(layer)
        if bbox is None:
            stats.skip(
                "layer_outside_extent",
                f"layer {layer_id} has no usable extent",
            )
            return
        layer_crs = str(_field(layer, "crs", "") or "")
        if project_crs and layer_crs and layer_crs != project_crs:
            stats.skip(
                "layer_outside_extent",
                f"layer {layer_id} CRS {layer_crs} ≠ workarea CRS "
                f"{project_crs}; comparison needs a transform",
            )
            return
        stats.count("layer_outside_extent")
        xmin, ymin, xmax, ymax = bbox
        wxmin, wymin, wxmax, wymax = ref_box
        if xmax < wxmin or xmin > wxmax or ymax < wymin or ymin > wymax:
            issues.append(
                make_issue(
                    rule="layer_outside_extent",
                    severity="warning",
                    message=(
                        f"图层 {layer_id} 完全位于工区范围之外"
                        f"（图层 {[round(v, 2) for v in bbox]} vs 工区 "
                        f"{[round(v, 2) for v in ref_box]}）"
                    ),
                    feature_kind="layer",
                    ref=layer_id,
                    extra={
                        "layer_id": layer_id,
                        "layer_bbox": list(bbox),
                        "workarea_bbox": list(ref_box),
                    },
                )
            )

    user_layer_ids: set[str] = set()
    for layer in getattr(project, "user_vector_layers", None) or []:
        user_layer_ids.add(str(_field(layer, "id", "")))
        _check(layer)
    for layer in _snapshot_layers(snapshot):
        if str(_field(layer, "id", "")) in user_layer_ids:
            continue  # already checked through the authoritative store
        _check(layer)
    return issues


def _stale_issues(
    project: Any,
    state: MappingWorkspaceState | None,
    catalog: Any,
    stale_summary: Any,
    stats: _RuleStats,
) -> list[dict]:
    """Reuse the MappingDependencyService freshness summary (§14 stale)."""
    summary = stale_summary
    if summary is None:
        if state is None:
            stats.skip(
                "stale_input", "no workspace state — staleness not computable"
            )
            return []
        from paleo_workbench.mapping_workspace.dependencies import (
            MappingDependencyService,
        )

        try:
            summary = MappingDependencyService().evaluate(
                project, state, catalog
            )
        except Exception:  # noqa: BLE001 — freshness must never break QA
            stats.skip("stale_input", "dependency evaluation failed")
            logger.warning("staleness evaluation failed", exc_info=True)
            return []
    issues: list[dict] = []
    for entry in getattr(summary, "artifacts", ()) or ():
        stats.count("stale_input")
        if not getattr(entry, "is_problem", False):
            continue
        status = str(getattr(entry, "status", "").value)
        issues.append(
            make_issue(
                rule="stale_input",
                severity="error" if status == "missing_input" else "warning",
                message=(
                    f"成果 {getattr(entry, 'artifact_key', '')} 输入"
                    f"{getattr(entry, 'status_label', status)}："
                    f"{getattr(entry, 'detail', '')}"
                ),
                feature_kind="artifact",
                ref=str(getattr(entry, "artifact_key", "")),
                extra={
                    "artifact_key": str(getattr(entry, "artifact_key", "")),
                    "status": status,
                    "upstream_culprits": list(
                        getattr(entry, "upstream_culprits", ()) or ()
                    ),
                },
            )
        )
    return issues


def _missing_source_issues(
    project: Any, snapshot: Any, state: MappingWorkspaceState | None,
    catalog: Any, stats: _RuleStats,
) -> list[dict]:
    """Layer references an absent catalog version or file."""
    issues: list[dict] = []
    surfaces = 0

    def _resolve(version_id: str) -> bool:
        try:
            return catalog.resolve_version(version_id) is not None
        except Exception:  # noqa: BLE001 — catalog may raise on unknown ids
            return False

    if catalog is not None:
        for layer in _snapshot_layers(snapshot):
            version_id = str(_field(layer, "source_version_id", "") or "")
            if not version_id:
                continue
            surfaces += 1
            stats.count("missing_source")
            if not _resolve(version_id):
                issues.append(
                    make_issue(
                        rule="missing_source",
                        severity="error",
                        message=(
                            f"图层 {_field(layer, 'id', '')} 引用的数据版本 "
                            f"{version_id} 在目录中不存在（已被清理？）"
                        ),
                        feature_kind="layer",
                        ref=str(_field(layer, "id", "")),
                        extra={
                            "layer_id": str(_field(layer, "id", "")),
                            "version_id": version_id,
                        },
                    )
                )
        if state is not None:
            for layer_id, record in state.memberships.items():
                version_id = str(record.source_version_id or "")
                if not version_id:
                    continue
                surfaces += 1
                stats.count("missing_source")
                if not _resolve(version_id):
                    issues.append(
                        make_issue(
                            rule="missing_source",
                            severity="error",
                            message=(
                                f"图层 {layer_id} 溯源钉住的输入版本 "
                                f"{version_id} 缺失"
                            ),
                            feature_kind="layer",
                            ref=layer_id,
                            extra={
                                "layer_id": layer_id,
                                "version_id": version_id,
                            },
                        )
                    )
    for layer in _snapshot_layers(snapshot):
        if str(_field(layer, "layer_type", "")) != "raster_source":
            continue
        path = _field(layer, "renderer_payload", None)
        if not isinstance(path, str) or not path:
            continue
        surfaces += 1
        stats.count("missing_source")
        if not Path(path).exists():
            issues.append(
                make_issue(
                    rule="missing_source",
                    severity="error",
                    message=f"栅格图层 {_field(layer, 'id', '')} 源文件缺失：{path}",
                    feature_kind="layer",
                    ref=str(_field(layer, "id", "")),
                    extra={"layer_id": str(_field(layer, "id", "")),
                           "source_path": path},
                )
            )
    for ref_layer in getattr(project, "workstation_reference_layers", None) or []:
        source_path = str(_field(ref_layer, "source_path", "") or "")
        status = str(_field(ref_layer, "status", "") or "")
        if not source_path and status in ("", "ready"):
            continue
        surfaces += 1
        stats.count("missing_source")
        if status in ("offline", "failed"):
            issues.append(
                make_issue(
                    rule="missing_source",
                    severity="warning",
                    message=(
                        f"参考图层 {_field(ref_layer, 'name', '')} 状态为 {status}"
                        f"：{_field(ref_layer, 'error_message', '')}"
                    ),
                    feature_kind="layer",
                    ref=str(_field(ref_layer, "id", "")),
                    extra={"layer_id": str(_field(ref_layer, "id", "")),
                           "status": status},
                )
            )
        elif source_path and not Path(source_path).exists():
            issues.append(
                make_issue(
                    rule="missing_source",
                    severity="error",
                    message=(
                        f"参考图层 {_field(ref_layer, 'name', '')} "
                        f"源文件缺失：{source_path}"
                    ),
                    feature_kind="layer",
                    ref=str(_field(ref_layer, "id", "")),
                    extra={"layer_id": str(_field(ref_layer, "id", "")),
                           "source_path": source_path},
                )
            )
    if surfaces == 0:
        stats.skip(
            "missing_source",
            "no layer carries a catalog version id, raster file path or "
            "reference-layer status to verify",
        )
    return issues


def _renderer_domain_issues(
    project: Any, snapshot: Any, state: MappingWorkspaceState | None,
    stats: _RuleStats,
) -> list[dict]:
    """Categorized renderer values must fall inside the spec's value domain.

    The domain authority is GeologicalLayerSpec (V2 registry) — checked ONLY
    where the layer's role is known through workspace membership; an unknown
    role is skipped honestly, never guessed.
    """
    from paleo_workbench.mapping_workspace.geological_layer_spec import (
        spec_for_role,
    )

    if state is None or not state.memberships:
        stats.skip(
            "renderer_domain_mismatch",
            "no layer roles recorded (workspace state empty) — domain check "
            "needs the role→spec binding",
        )
        return []
    layers_by_id: dict[str, Any] = {}
    for layer in getattr(project, "user_vector_layers", None) or []:
        layers_by_id[str(_field(layer, "id", ""))] = layer
    for layer in _snapshot_layers(snapshot):
        layers_by_id.setdefault(str(_field(layer, "id", "")), layer)

    issues: list[dict] = []
    known_roles = 0
    for layer_id, record in state.memberships.items():
        role = getattr(record, "role", None)
        try:
            spec = spec_for_role(role)
        except KeyError:
            stats.skip(
                "renderer_domain_mismatch",
                f"layer {layer_id} role {role!r} has no GeologicalLayerSpec",
            )
            continue
        known_roles += 1
        layer = layers_by_id.get(str(layer_id))
        if layer is None:
            stats.skip(
                "renderer_domain_mismatch",
                f"layer {layer_id} (role {getattr(role, 'value', role)}) "
                "not present in the project/snapshot",
            )
            continue
        style = _field(layer, "style", None)
        if not isinstance(style, Mapping) or str(style.get("renderer") or "") != "categorized":
            stats.count("renderer_domain_mismatch")
            continue
        binding = getattr(spec, "renderer_binding", None)
        field_name = str(style.get("field") or (getattr(binding, "field", "") or ""))
        if not field_name:
            stats.skip(
                "renderer_domain_mismatch",
                f"layer {layer_id} categorized style declares no field and "
                f"spec {spec.spec_id} binds none",
            )
            continue
        spec_field = next(
            (f for f in spec.fields if f.name == field_name), None
        )
        if spec_field is None or not spec_field.choices:
            stats.skip(
                "renderer_domain_mismatch",
                f"spec {spec.spec_id} declares no closed domain for field "
                f"{field_name} — nothing to check against",
            )
            continue
        stats.count("renderer_domain_mismatch")
        domain = set(spec_field.choices)
        offenders: list[str] = []
        for feature in _field(layer, "features", None) or ():
            value = (_field(feature, "properties", None) or {}).get(field_name)
            if value is None:
                continue
            text = str(value)
            if text not in domain and text not in offenders:
                offenders.append(text)
        if offenders:
            issues.append(
                make_issue(
                    rule="renderer_domain_mismatch",
                    severity="warning",
                    message=(
                        f"图层 {layer_id}（角色 {getattr(role, 'value', '')}）"
                        f"字段 {field_name} 出现域外值 {sorted(offenders)}——"
                        f"规范 {spec.spec_id} 闭域为 {sorted(domain)}"
                    ),
                    feature_kind="layer",
                    ref=layer_id,
                    extra={
                        "layer_id": layer_id,
                        "field": field_name,
                        "out_of_domain": sorted(offenders),
                        "spec_id": spec.spec_id,
                    },
                )
            )
    if known_roles == 0:
        stats.skip(
            "renderer_domain_mismatch",
            "no membership carries a spec-bound role",
        )
    return issues


def _legend_issues(
    project: Any, snapshot: Any, stats: _RuleStats
) -> list[dict]:
    """Legend-family composition elements with nothing to show."""
    compositions = _compositions(project)
    if not compositions:
        stats.skip("legend_empty", "no compositions on the project")
        return []
    issues: list[dict] = []
    from paleo_workbench.mapping.layout_export import _legend_backed_types

    for composition in compositions:
        comp_id = str(_field(composition, "id", "") or "")
        for element in _field(composition, "elements", None) or ():
            etype = _field(element, "element_type", "")
            type_value = str(getattr(etype, "value", etype) or "")
            if type_value not in _LEGEND_FAMILY_VALUES:
                continue
            if _field(element, "visible", True) is False:
                continue
            stats.count("legend_empty")
            items = _field(_field(element, "properties", None) or {}, "items", None)
            if items:
                continue  # explicit legend items → resolvable
            # legend-backed elements resolve from the mirrored layers
            if type_value in {
                str(getattr(t, "value", t))
                for t in _legend_backed_types(snapshot)
            }:
                continue
            issues.append(
                make_issue(
                    rule="legend_empty",
                    severity="warning",
                    message=(
                        f"组图 {comp_id} 的 {type_value} 组件 "
                        f"{_field(element, 'id', '')} 无可解析的图例项"
                        "（items 为空且镜像中无对应图层）"
                    ),
                    feature_kind="composition_element",
                    feature_id=str(_field(element, "id", "") or ""),
                    ref=comp_id,
                    extra={
                        "composition_id": comp_id,
                        "element_type": type_value,
                    },
                )
            )
    return issues


def _furniture_issues(project: Any, stats: _RuleStats) -> list[dict]:
    """Template-built compositions must keep the core furniture set."""
    compositions = _compositions(project)
    if not compositions:
        stats.skip("core_furniture_missing", "no compositions on the project")
        return []
    issues: list[dict] = []
    checked = 0
    for composition in compositions:
        comp_id = str(_field(composition, "id", "") or "")
        metadata = _field(composition, "metadata", None) or {}
        if not (metadata.get("template_id") if isinstance(metadata, Mapping) else None):
            stats.skip(
                "core_furniture_missing",
                f"composition {comp_id} records no template expectation "
                "(metadata.template_id absent) — furniture set not promised",
            )
            continue
        checked += 1
        visible_values = {
            str(getattr(_field(el, "element_type", ""), "value",
                        _field(el, "element_type", "")) or "")
            for el in _field(composition, "elements", None) or ()
            if _field(el, "visible", True) is not False
        }
        for required in _CORE_FURNITURE_VALUES:
            stats.count("core_furniture_missing")
            if required not in visible_values:
                issues.append(
                    make_issue(
                        rule="core_furniture_missing",
                        severity="warning",
                        message=(
                            f"模板组图 {comp_id} 缺少核心成图组件 {required}"
                        ),
                        feature_kind="composition",
                        ref=comp_id,
                        extra={
                            "composition_id": comp_id,
                            "missing": required,
                            "template_id": metadata.get("template_id"),
                        },
                    )
                )
    if checked == 0:
        stats.skip(
            "core_furniture_missing",
            "no composition is template-built; furniture set not promised",
        )
    return issues


def _confidence_issues(
    project: Any, stats: _RuleStats, *, threshold: float
) -> list[dict]:
    """Prediction overlays whose probability stats sit below threshold."""
    tasks = [
        task
        for task in getattr(project, "prediction_tasks", None) or []
        if _field(task, "probability_summary", None)
    ]
    if not tasks:
        stats.skip(
            "low_confidence", "no prediction overlays with probability stats"
        )
        return []
    issues: list[dict] = []
    for task in tasks:
        stats.count("low_confidence")
        summary = dict(_field(task, "probability_summary", None) or {})
        task_id = str(_field(task, "id", ""))
        mean = summary.get("mean")
        minimum = summary.get("min")
        low_regions = int(summary.get("low_confidence_regions") or 0)
        below = (
            isinstance(mean, (int, float)) and float(mean) < threshold
        ) or (
            isinstance(minimum, (int, float)) and float(minimum) < threshold
        )
        if below or low_regions:
            issues.append(
                make_issue(
                    rule="low_confidence",
                    severity="warning",
                    message=(
                        f"预测 {task_id}（{_field(task, 'name', '')}）置信度低："
                        f"mean={mean} min={minimum} 阈值={threshold:.2f}"
                        f" 低置信区域 {low_regions} 个"
                    ),
                    feature_kind="prediction_task",
                    ref=task_id,
                    extra={
                        "prediction_task_id": task_id,
                        "mean": mean,
                        "min": minimum,
                        "threshold": threshold,
                        "low_confidence_regions": low_regions,
                    },
                )
            )
    return issues


def _capability_says_qgis_available(capability: Mapping[str, Any] | None) -> bool | None:
    if capability is None:
        return None
    if "qgis_available" in capability:
        return bool(capability["qgis_available"])
    engine = str(capability.get("engine") or capability.get("backend") or "")
    if engine:
        return engine.lower() in ("qgis", "qgis_layout")
    return None


def _fallback_renderer_issues(
    snapshot: Any, capability: Mapping[str, Any] | None, stats: _RuleStats
) -> list[dict]:
    """Degraded rendering path disclosed: QGIS unavailable WITH scalar data."""
    available = _capability_says_qgis_available(capability)
    if available is None:
        stats.skip(
            "fallback_renderer",
            "no capability snapshot provided — renderer degradation "
            "cannot be asserted",
        )
        return []
    layers = _snapshot_layers(snapshot)
    scalar_layers = [
        layer
        for layer in layers
        if str(_field(layer, "layer_type", "")) in ("scalar_grid", "grid")
    ]
    if not scalar_layers:
        stats.count("fallback_renderer")
        return []
    if available:
        stats.count("fallback_renderer")
        return []
    reason = str((capability or {}).get("reason") or "")
    issues: list[dict] = []
    for layer in scalar_layers:
        stats.count("fallback_renderer")
        layer_id = str(_field(layer, "id", ""))
        issues.append(
            make_issue(
                rule="fallback_renderer",
                severity="warning",
                message=(
                    f"QGIS 渲染不可用但标量图层 {layer_id} 存在——栅格走降级"
                    f"渲染路径（RGBA 镜像而非 QGIS 伪彩色）{('：' + reason) if reason else ''}，"
                    "屏显与导出可能存在符号差异"
                ),
                feature_kind="layer",
                ref=layer_id,
                extra={
                    "layer_id": layer_id,
                    "qgis_available": False,
                    "reason": reason,
                },
            )
        )
    return issues


def _maturity_issues(
    project: Any, state: MappingWorkspaceState | None, stats: _RuleStats
) -> list[dict]:
    """Export-bound maturity: below reviewed while a MapProduct exists."""
    if not getattr(project, "map_products", None):
        stats.skip(
            "unpublished_data_in_export",
            "no MapProduct record — rule is scoped to export-bound projects",
        )
        return []
    if state is None or not state.artifact_maturity:
        stats.skip(
            "unpublished_data_in_export",
            "no artifact maturity recorded — nothing to assert (unrecorded "
            "maturity is never guessed as draft)",
        )
        return []
    issues: list[dict] = []
    for artifact_key, maturity in sorted(state.artifact_maturity.items()):
        stats.count("unpublished_data_in_export")
        if maturity not in MATURITY_ORDER:
            stats.skip(
                "unpublished_data_in_export",
                f"artifact {artifact_key} carries unknown maturity {maturity!r}",
            )
            continue
        if MATURITY_ORDER[maturity] < MATURITY_ORDER[_MATURITY_EXPORT_FLOOR]:
            layer_id = ""
            if ":" in artifact_key:
                tail = artifact_key.split(":", 1)[1]
                if not tail.startswith(("factor", "mapproduct")):
                    layer_id = tail
            issues.append(
                make_issue(
                    rule="unpublished_data_in_export",
                    severity="warning",
                    message=(
                        f"成果 {artifact_key} 成熟度为 {maturity}"
                        f"（低于 {_MATURITY_EXPORT_FLOOR}）却参与了"
                        "绑定导出的成图产品"
                    ),
                    feature_kind="artifact",
                    ref=artifact_key,
                    extra={
                        "artifact_key": artifact_key,
                        "maturity": maturity,
                        "layer_id": layer_id,
                    },
                )
            )
    return issues


def _symbol_library_probe() -> tuple[Callable[[str], bool] | None, str]:
    """Probe the V2 symbols library (:mod:`mapping.geological_symbols`).

    The canonical surface is ``symbol_by_id`` (raises ``KeyError`` on
    unknown ids, alias-aware). Fallback probes keep the rule alive if the
    parallel-developed module shifts shape; ``None`` when the module is
    absent or exposes none of the recognized surfaces (honest skip).
    """
    try:
        from paleo_workbench.mapping import geological_symbols
    except ImportError:
        return None, "absent"

    lookup = getattr(geological_symbols, "symbol_by_id", None)
    if callable(lookup):
        def _probe(symbol_id: str) -> bool:
            try:
                return lookup(symbol_id) is not None
            except KeyError:
                return False

        return _probe, "symbol_by_id"
    for name in ("symbol_exists", "has_symbol"):
        fn = getattr(geological_symbols, name, None)
        if callable(fn):
            return fn, name
    get = getattr(geological_symbols, "get_symbol", None)
    if callable(get):
        return lambda sid: get(sid) is not None, "get_symbol"
    registry = getattr(geological_symbols, "GEOLOGICAL_SYMBOLS", None)
    if isinstance(registry, Mapping):
        return lambda sid: sid in registry, "GEOLOGICAL_SYMBOLS"
    return None, "unrecognized"


def _style_binding_issues(
    project: Any, snapshot: Any, stats: _RuleStats
) -> list[dict]:
    """style_binding must reference a symbol present in the V2 library."""
    probe, surface = _symbol_library_probe()
    if probe is None:
        stats.skip(
            "style_binding_unknown",
            f"geological_symbols library {surface} — rule cannot run",
        )
        return []
    issues: list[dict] = []
    checked = 0

    def _binding_id(style: Any, metadata: Any) -> str:
        for source in (style, metadata):
            if not isinstance(source, Mapping):
                continue
            binding = source.get("style_binding")
            if isinstance(binding, str) and binding:
                return binding
            if isinstance(binding, Mapping):
                return str(binding.get("symbol_id") or "")
        return ""

    for layer in getattr(project, "user_vector_layers", None) or []:
        symbol_id = _binding_id(
            _field(layer, "style", None), _field(layer, "metadata", None)
        )
        if not symbol_id:
            continue
        checked += 1
        stats.count("style_binding_unknown")
        if not probe(symbol_id):
            issues.append(
                make_issue(
                    rule="style_binding_unknown",
                    severity="warning",
                    message=(
                        f"图层 {_field(layer, 'id', '')} 的 style_binding 引用"
                        f"符号 {symbol_id}，但 V2 符号库中不存在"
                    ),
                    feature_kind="layer",
                    ref=str(_field(layer, "id", "")),
                    extra={
                        "layer_id": str(_field(layer, "id", "")),
                        "symbol_id": symbol_id,
                    },
                )
            )
    for layer in _snapshot_layers(snapshot):
        symbol_id = _binding_id(
            _field(layer, "style", None), _field(layer, "metadata", None)
        )
        if not symbol_id:
            continue
        checked += 1
        stats.count("style_binding_unknown")
        if not probe(symbol_id):
            layer_id = str(_field(layer, "id", ""))
            issues.append(
                make_issue(
                    rule="style_binding_unknown",
                    severity="warning",
                    message=f"快照图层 {layer_id} 的 style_binding 引用未知符号 {symbol_id}",
                    feature_kind="layer",
                    ref=layer_id,
                    extra={"layer_id": layer_id, "symbol_id": symbol_id},
                )
            )
    if checked == 0:
        stats.skip(
            "style_binding_unknown", "no layer records a style_binding"
        )
    return issues


def _raster_range_issues(snapshot: Any, stats: _RuleStats) -> list[dict]:
    """Scalar-layer manual_range hi<=lo / NaN stats (§14 raster range)."""
    from paleo_workbench.mapping.scalar_style import ScalarStyleSpec

    scalar_layers = [
        layer
        for layer in _snapshot_layers(snapshot)
        if str(_field(layer, "layer_type", "")) in ("scalar_grid", "grid")
    ]
    if not scalar_layers:
        stats.skip("raster_range_invalid", "no scalar layers in the snapshot")
        return []
    issues: list[dict] = []

    def _bad_range(lo: Any, hi: Any) -> str | None:
        try:
            lo_f, hi_f = float(lo), float(hi)
        except (TypeError, ValueError):
            return f"non-numeric range [{lo!r}, {hi!r}]"
        if lo_f != lo_f or hi_f != hi_f:  # NaN check
            return f"NaN in range [{lo!r}, {hi!r}]"
        if not hi_f > lo_f:
            return f"hi<=lo in range [{lo_f}, {hi_f}]"
        return None

    for layer in scalar_layers:
        stats.count("raster_range_invalid")
        layer_id = str(_field(layer, "id", ""))
        style = _field(layer, "style", None)
        style = style if isinstance(style, Mapping) else {}
        problem: str | None = None
        nested = style.get("scalar_style")
        if isinstance(nested, Mapping) and nested:
            try:
                ScalarStyleSpec.from_dict(dict(nested))
            except ValueError as exc:
                problem = str(exc)
        if problem is None:
            manual = style.get("manual_range") or nested.get("manual_range") if isinstance(nested, Mapping) else style.get("manual_range")
            if isinstance(manual, (list, tuple)) and len(manual) == 2:
                problem = _bad_range(manual[0], manual[1])
        if problem is None:
            legacy = style.get("color_range")
            if isinstance(legacy, (list, tuple)) and len(legacy) == 2:
                problem = _bad_range(legacy[0], legacy[1])
        if problem is None:
            stats_range = style.get("value_range")
            if isinstance(stats_range, (list, tuple)) and len(stats_range) == 2:
                problem = _bad_range(stats_range[0], stats_range[1])
        if problem is None:
            grid_stats = _field(layer, "metadata", None) or {}
            if isinstance(grid_stats, Mapping):
                for key in ("min", "max"):
                    value = grid_stats.get(key)
                    if isinstance(value, float) and value != value:
                        problem = f"NaN {key} in grid stats"
                        break
        if problem:
            issues.append(
                make_issue(
                    rule="raster_range_invalid",
                    severity="error",
                    message=f"标量图层 {layer_id} 的显示范围无效：{problem}",
                    feature_kind="layer",
                    ref=layer_id,
                    extra={"layer_id": layer_id, "problem": problem},
                )
            )
    return issues


def _factor_group_issues(
    state: MappingWorkspaceState | None, stats: _RuleStats
) -> list[dict]:
    """factor.<task> groups must carry the full FACTOR_CHILD_ORDER set."""
    if state is None:
        stats.skip("broken_factor_group", "no workspace state — groups unknown")
        return []
    tree = state.tree or {}
    if not tree:
        stats.skip("broken_factor_group", "workspace tree empty — no groups")
        return []

    def _walk_group(node: Any) -> Iterable[tuple[str, list[str]]]:
        group_id = str(_field(node, "id", _field(node, "group_id", "")) or "")
        children = list(_field(node, "children", None) or ())
        layer_ids: list[str] = []
        for child in children:
            child_type = str(_field(child, "type", "") or "")
            if child_type == "layer" or "layer_id" in (
                child if isinstance(child, Mapping) else {}
            ):
                layer_ids.append(str(_field(child, "id", _field(child, "layer_id", "")) or ""))
            else:
                for _gid, _layers in _walk_group(child):
                    if is_factor_group(_gid):
                        yield _gid, _layers
                    layer_ids.extend(_layers)
        yield group_id, layer_ids

    issues: list[dict] = []
    saw_factor_group = False
    for group_id, layer_ids in _walk_group(tree):
        if not is_factor_group(group_id):
            continue
        saw_factor_group = True
        stats.count("broken_factor_group")
        present_roles = {
            state.memberships[lid].role
            for lid in layer_ids
            if lid in state.memberships
        }
        missing = [
            role.value for role in FACTOR_CHILD_ORDER if role not in present_roles
        ]
        if missing:
            issues.append(
                make_issue(
                    rule="broken_factor_group",
                    severity="warning",
                    message=(
                        f"单因素组 {group_id}（任务 {factor_task_of_group(group_id)}）"
                        f"缺少子角色 {missing}——FACTOR_CHILD_ORDER 应为 "
                        f"{[r.value for r in FACTOR_CHILD_ORDER]}"
                    ),
                    feature_kind="layer_group",
                    ref=group_id,
                    extra={
                        "group_id": group_id,
                        "missing_roles": missing,
                        "factor_task_id": factor_task_of_group(group_id),
                    },
                )
            )
    if not saw_factor_group:
        stats.skip("broken_factor_group", "no factor.<task> groups in the tree")
    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_cartographic_qa(
    project: Any,
    *,
    snapshot: Any = None,
    capability: Mapping[str, Any] | None = None,
    stale_summary: Any = None,
    catalog: Any = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> tuple[list[dict], dict[str, dict[str, Any]]]:
    """Evaluate every §14 rule; return ``(issues, summary)``.

    ``project`` — ProjectDocument (duck-typed; compositions may hang off a
    ``compositions`` attribute). ``snapshot`` — the MapRenderSnapshot (or
    layer sequence) mirrored into the render stack. ``capability`` — a
    mapping with ``qgis_available`` (or ``engine``/``backend``) and an
    optional ``reason``. ``stale_summary`` — a precomputed
    MappingDependencyService ``StaleSummary``; without one (and with a
    workspace state) the service is evaluated inline using ``catalog``.
    """
    stats = _RuleStats()
    state = _workspace_state(project)
    issues: list[dict] = []
    issues += _crs_issues(project, snapshot, stats)
    issues += _geometry_issues(project, stats)
    issues += _outside_extent_issues(project, snapshot, stats)
    issues += _stale_issues(project, state, catalog, stale_summary, stats)
    issues += _missing_source_issues(project, snapshot, state, catalog, stats)
    issues += _renderer_domain_issues(project, snapshot, state, stats)
    issues += _legend_issues(project, snapshot, stats)
    issues += _furniture_issues(project, stats)
    issues += _confidence_issues(project, stats, threshold=confidence_threshold)
    issues += _fallback_renderer_issues(snapshot, capability, stats)
    issues += _maturity_issues(project, state, stats)
    issues += _style_binding_issues(project, snapshot, stats)
    issues += _raster_range_issues(snapshot, stats)
    issues += _factor_group_issues(state, stats)
    return issues, stats.summary()


def collect_cartographic_qa_issues(
    project: Any,
    *,
    snapshot: Any = None,
    capability: Mapping[str, Any] | None = None,
    stale_summary: Any = None,
    catalog: Any = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> list[dict]:
    """§14 cartographic QA issues localized to layer/feature/geometry.

    The list-only twin of :func:`collect_cartographic_qa` — same rules,
    same honesty, for callers that only consume issues (the stage QA
    action composes this beside
    :func:`workflow.map_qa_rules.collect_extended_qc_issues`).
    """
    issues, _summary = collect_cartographic_qa(
        project,
        snapshot=snapshot,
        capability=capability,
        stale_summary=stale_summary,
        catalog=catalog,
        confidence_threshold=confidence_threshold,
    )
    return issues


def cartographic_rule_summary(
    project: Any,
    *,
    snapshot: Any = None,
    capability: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, dict[str, Any]]:
    """Evaluate the rules and return only the summary (evaluated/skipped)."""
    _issues, summary = collect_cartographic_qa(
        project, snapshot=snapshot, capability=capability, **kwargs
    )
    return summary
